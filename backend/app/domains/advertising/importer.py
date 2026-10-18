"""Importing linked ad accounts (Phase 3, tasks 3-05 …; PHASE_03_PLAN §9).

Platform-neutral: the core asks an ``AdvertisingProvider`` for the account's state, its
structure and (from 3-06) its daily figures, and stores them in the advertising tables. Like
the commerce import, the work runs as a **chain of short jobs** (``advertising.import_step``),
one step each, under a per-account lock; ``ad_sync_state.import_job_id`` names the only step
allowed to continue, so a duplicated job message stops at once.

Steps of a chain (``ad_sync_state.import_cursor``): ``structure`` → ``perf:<first>:<last>`` (one
step per calendar-month slice of daily figures, four levels each, so a 13-month first import
costs about 56 operations) → ``done``. Each slice **replaces** the stored figures of its days,
so corrections and removed activity never leave stale numbers; the account level gets a real
zero for every day Google reports nothing (A10: zero only where the platform says zero).
Removed campaigns, ad groups and ads are kept (status
``removed``) so their history stays readable; items the platform stops listing are left as
they are, never deleted on absence.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domains.advertising.models import (
    Ad,
    AdAccount,
    AdBudget,
    AdCampaign,
    AdGroup,
    AdPerformanceDaily,
    AdSyncState,
)
from app.domains.audit.service import Actor, record_audit
from app.domains.integrations.jobs import call_provider
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.integrations.tokens import AccountBusy, account_lock, usable_secrets
from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError, create_job
from app.providers.base.errors import ProviderError, ResourceUnavailableError
from app.providers.base.interfaces import AdvertisingProvider, PlatformProvider
from app.providers.base.types import (
    AdAccountRef,
    AdBudgetRecord,
    AdCampaignRecord,
    AdGroupRecord,
    AdLevel,
    AdPerformanceRecord,
    AdRecord,
    AdStructureRecord,
    ProviderCategory,
    ResourceKind,
)
from app.runtime import Runtime

logger = logging.getLogger("advegax.advertising.importer")

JOB_AD_IMPORT_STEP = "advertising.import_step"
WORKER = Actor("worker", None)
IMPORT_LOCK_TTL_SECONDS = 15 * 60  # one step is a handful of short reads
STEP_STRUCTURE = "structure"
STEP_DONE = "done"
STEP_PERFORMANCE = "perf"
ACCOUNT_KEY = "account"  # entity_key of account-level rows


def advertising_provider(provider: PlatformProvider) -> AdvertisingProvider | None:
    if provider.category is not ProviderCategory.ADVERTISING:
        return None
    if not all(
        hasattr(provider, m) for m in ("read_account", "read_structure", "read_performance")
    ):
        return None
    return cast(AdvertisingProvider, provider)


def local_today(rt: Runtime, timezone: str) -> date:
    return rt.clock.now().astimezone(ZoneInfo(timezone)).date()


# ------------------------------------------------------------------ linking
def on_ad_account_linked(
    session: Session,
    rt: Runtime,
    *,
    resource: ExternalResource,
    connection: ExternalConnection,
    user_id: uuid.UUID | None,
) -> AdAccount | None:
    """Called inside the link transaction: create the ad account (first link) and start its
    import. Returns ``None`` for anything that is not an advertising account."""
    provider = advertising_provider(rt.providers.get(connection.provider))
    if provider is None or resource.kind != ResourceKind.AD_ACCOUNT.value:
        return None
    if resource.currency is None or resource.timezone is None:
        return None  # linking is refused before this for such accounts (3-04)
    account = session.execute(
        select(AdAccount).where(AdAccount.external_resource_id == resource.id)
    ).scalar_one_or_none()
    if account is None:
        today = local_today(rt, resource.timezone)
        account = AdAccount(
            organization_id=resource.organization_id,
            external_resource_id=resource.id,
            provider=connection.provider,
            external_account_id=resource.external_id,
            name=resource.display_name,
            currency=resource.currency,
            timezone=resource.timezone,
            status="importing",
            platform_status="active",
            history_from=_shift(today, -rt.settings.ADS_HISTORY_WINDOW.days),
        )
        session.add(account)
        session.flush()
        session.add(AdSyncState(ad_account_id=account.id, organization_id=account.organization_id))
        session.flush()
    start_import(session, rt, account, requested_by=user_id)
    return account


def start_import(
    session: Session, rt: Runtime, account: AdAccount, *, requested_by: uuid.UUID | None
) -> uuid.UUID:
    """(Re)start the chain from the structure step."""
    state = session.get(AdSyncState, account.id, with_for_update=True)
    if state is None:
        state = AdSyncState(ad_account_id=account.id, organization_id=account.organization_id)
        session.add(state)
    now = rt.clock.now()
    initial = account.first_import_completed_at is None
    if initial:
        account.status = "importing"
        state.import_progress = 0
    state.sync_mode = "initial" if initial else "nightly"
    state.sync_started_at = now
    state.import_cursor = STEP_STRUCTURE
    state.last_error_code = state.last_error_at = None
    job = _schedule(session, rt, account, state, requested_by=requested_by)
    record_audit(
        session,
        organization_id=account.organization_id,
        actor=Actor.user(requested_by) if requested_by else WORKER,
        action="ad_account.import_started",
        resource_type="ad_account",
        resource_id=account.id,
        metadata={"job_id": str(job), "mode": state.sync_mode},
    )
    return job


def _schedule(
    session: Session,
    rt: Runtime,
    account: AdAccount,
    state: AdSyncState,
    *,
    requested_by: uuid.UUID | None = None,
) -> uuid.UUID:
    job = create_job(
        session,
        rt,
        organization_id=account.organization_id,
        job_type=JOB_AD_IMPORT_STEP,
        subject_type="ad_account",
        subject_id=account.id,
        requested_by=requested_by,
    )
    state.import_job_id = job.id
    state.updated_at = rt.clock.now()
    return job.id


# ------------------------------------------------------------------ the step
@dataclass(frozen=True)
class _Context:
    org_id: uuid.UUID
    account_id: uuid.UUID
    connection_id: uuid.UUID
    ref: AdAccountRef
    step: str
    first_import: bool


def import_step(rt: Runtime, job: ClaimedJob) -> None:
    if job.organization_id is None or job.subject_id is None:
        raise JobSubjectGoneError()
    org_id, account_id = job.organization_id, uuid.UUID(job.subject_id)
    try:
        with account_lock(
            rt.redis,
            f"ad-import-lock:{account_id}",
            wait_seconds=0,
            ttl_seconds=IMPORT_LOCK_TTL_SECONDS,
        ):
            again = _step(rt, job, org_id, account_id)
    except AccountBusy:
        logger.info("ad_import_step_busy", extra={"ad_account_id": str(account_id)})
        return
    if again:
        with rt.db.transaction(org_id=org_id) as session:
            account = session.get(AdAccount, account_id)
            state = session.get(AdSyncState, account_id, with_for_update=True)
            if account is not None and state is not None and state.import_job_id == job.id:
                _schedule(session, rt, account, state)


def _load(
    rt: Runtime, job: ClaimedJob, org_id: uuid.UUID, account_id: uuid.UUID
) -> tuple[_Context | None, AdvertisingProvider | None]:
    with rt.db.transaction(org_id=org_id) as session:
        row = session.execute(
            select(AdAccount, AdSyncState, ExternalResource, ExternalConnection)
            .join(AdSyncState, AdSyncState.ad_account_id == AdAccount.id)
            .join(ExternalResource, ExternalResource.id == AdAccount.external_resource_id)
            .join(ExternalConnection, ExternalConnection.id == ExternalResource.connection_id)
            .where(AdAccount.id == account_id, AdAccount.organization_id == org_id)
        ).one_or_none()
        if row is None:
            raise JobSubjectGoneError()
        account, state, resource, connection = row
        if state.import_job_id != job.id:
            return None, None  # a newer step owns the chain
        linked = session.execute(
            select(OrganizationResourceLink.id).where(
                OrganizationResourceLink.external_resource_id == resource.id,
                OrganizationResourceLink.status == "active",
            )
        ).first()
        if linked is None or connection.status != "active":
            state.import_job_id = None
            state.last_error_code = "link_ended" if linked is None else "connection_inactive"
            state.last_error_at = rt.clock.now()
            return None, None
        provider = advertising_provider(rt.providers.get(connection.provider))
        if provider is None:
            raise JobSubjectGoneError()
        return (
            _Context(
                org_id=org_id,
                account_id=account.id,
                connection_id=connection.id,
                ref=AdAccountRef(account.external_account_id, resource.access_hint),
                step=state.import_cursor or STEP_STRUCTURE,
                first_import=account.first_import_completed_at is None,
            ),
            provider,
        )


def _step(rt: Runtime, job: ClaimedJob, org_id: uuid.UUID, account_id: uuid.UUID) -> bool:
    """Run one step; ``True`` when another step follows. Temporary platform errors propagate
    (the job framework retries with back-off); an unusable account or a permanent error (or
    the last retry) ends the chain with a plain code on the account."""
    ctx, provider = _load(rt, job, org_id, account_id)
    if ctx is None or provider is None:
        return False
    try:
        if ctx.step == STEP_STRUCTURE:
            return _structure(rt, ctx, provider)
        if (span := performance_cursor(ctx.step)) is not None:
            return _performance(rt, ctx, provider, *span)
        _finish(rt, ctx)
        return False
    except ResourceUnavailableError as exc:
        _fail(rt, ctx, exc.code, health=True)
        return False
    except ProviderError as exc:
        if not exc.retryable or job.attempts >= job.max_attempts:
            _fail(rt, ctx, exc.code, health=False)
        raise


def _call(rt: Runtime, ctx: _Context, provider: AdvertisingProvider, fn: Any) -> Any:
    return call_provider(rt, provider, ctx.org_id, ctx.connection_id, fn)


def _structure(rt: Runtime, ctx: _Context, provider: AdvertisingProvider) -> bool:
    secrets = usable_secrets(rt, ctx.org_id, ctx.connection_id)
    state = _call(rt, ctx, provider, lambda: provider.read_account(secrets, ctx.ref))
    with rt.db.transaction(org_id=ctx.org_id) as session:
        account = session.get(AdAccount, ctx.account_id)
        assert account is not None
        account.name = state.name or account.name
        account.platform_status = state.platform_status
        account.health_checked_at = rt.clock.now()
        if state.platform_status != "active":
            account.health_code = "account_not_enabled"
        elif account.health_code == "account_not_enabled":
            account.health_code = None
        # Currency and time zone are fixed for the life of a Google Ads account; a change
        # would make stored figures inconsistent, so it is recorded, never applied silently.
        if (state.currency, state.timezone) != (account.currency, account.timezone):
            account.health_code = "account_details_changed"
    if state.platform_status != "active":
        _fail(rt, ctx, "account_not_enabled", health=True)
        return False
    records = list(_call(rt, ctx, provider, lambda: provider.read_structure(secrets, ctx.ref)))
    with rt.db.transaction(org_id=ctx.org_id) as session:
        counts = apply_structure(session, rt, ctx.org_id, ctx.account_id, records)
        sync = session.get(AdSyncState, ctx.account_id, with_for_update=True)
        assert sync is not None
        account = session.get(AdAccount, ctx.account_id)
        assert account is not None
        sync.import_cursor = _cursor(history_start(rt, account), local_today(rt, account.timezone))
        if ctx.first_import:
            sync.import_progress = 50
            record_audit(
                session,
                organization_id=ctx.org_id,
                actor=WORKER,
                action="ad_account.structure_imported",
                resource_type="ad_account",
                resource_id=ctx.account_id,
                metadata={"counts": counts},
            )
    return True


# ------------------------------------------------------------------ daily figures
def _cursor(first: date, last: date) -> str:
    return f"{STEP_PERFORMANCE}:{first.isoformat()}:{last.isoformat()}"


def performance_cursor(step: str) -> tuple[date, date] | None:
    """``perf:<first>:<last>`` → the days still to read; None for any other step."""
    parts = step.split(":")
    if len(parts) != 3 or parts[0] != STEP_PERFORMANCE:
        return None
    try:
        first, last = date.fromisoformat(parts[1]), date.fromisoformat(parts[2])
    except ValueError:
        return None
    return (first, last) if first <= last else None


def _shift(day: date, days: int) -> date:
    return date.fromordinal(day.toordinal() + days)


def month_slice(first: date, last: date) -> date:
    """The last day of the slice starting at ``first``: the end of its calendar month."""
    next_month = _shift(first.replace(day=28), 4).replace(day=1)
    return min(last, _shift(next_month, -1))


def history_start(rt: Runtime, account: AdAccount) -> date:
    if account.history_from is not None:
        return account.history_from
    today = local_today(rt, account.timezone)
    return _shift(today, -rt.settings.ADS_HISTORY_WINDOW.days)


def _performance(
    rt: Runtime, ctx: _Context, provider: AdvertisingProvider, first: date, last: date
) -> bool:
    end = month_slice(first, last)
    secrets = usable_secrets(rt, ctx.org_id, ctx.connection_id)
    records: dict[AdLevel, list[AdPerformanceRecord]] = {}
    for level in AdLevel:
        records[level] = list(
            _call(
                rt,
                ctx,
                provider,
                lambda level=level: provider.read_performance(secrets, ctx.ref, level, first, end),
            )
        )
    with rt.db.transaction(org_id=ctx.org_id) as session:
        account = session.get(AdAccount, ctx.account_id)
        sync = session.get(AdSyncState, ctx.account_id, with_for_update=True)
        assert account is not None
        assert sync is not None
        written = apply_performance(session, rt, account, first, end, records)
        more = end < last
        sync.import_cursor = _cursor(_shift(end, 1), last) if more else STEP_DONE
        if ctx.first_import:
            start = history_start(rt, account)
            span = max(1, (last - start).days + 1)
            done = (end - start).days + 1
            sync.import_progress = min(99, 50 + (50 * done) // span)
        sync.updated_at = rt.clock.now()
        logger.info(
            "ad_performance_slice_imported",
            extra={"ad_account_id": str(ctx.account_id), "first": str(first), "rows": written},
        )
    return True


def apply_performance(
    session: Session,
    rt: Runtime,
    account: AdAccount,
    first: date,
    last: date,
    records: dict[AdLevel, list[AdPerformanceRecord]],
) -> int:
    """Replace the stored figures of ``first`` … ``last`` for each level read. Rows are
    linked to the structure where it is known; duplicates of one entity and day
    are never summed: the first is kept and the rest are counted as skipped."""
    now = rt.clock.now()
    campaigns = {
        c.external_campaign_id: c.id
        for c in session.execute(
            select(AdCampaign).where(AdCampaign.ad_account_id == account.id)
        ).scalars()
    }
    groups = {
        g.external_ad_group_id: g.id
        for g in session.execute(
            select(AdGroup)
            .join(AdCampaign, AdCampaign.id == AdGroup.campaign_id)
            .where(AdCampaign.ad_account_id == account.id)
        ).scalars()
    }
    ads = {
        (a.ad_group_id, a.external_ad_id): a.id
        for a in session.execute(
            select(Ad)
            .join(AdGroup, AdGroup.id == Ad.ad_group_id)
            .join(AdCampaign, AdCampaign.id == AdGroup.campaign_id)
            .where(AdCampaign.ad_account_id == account.id)
        ).scalars()
    }
    written = skipped = 0
    for level, rows in records.items():
        session.execute(
            delete(AdPerformanceDaily).where(
                AdPerformanceDaily.ad_account_id == account.id,
                AdPerformanceDaily.level == level.value,
                AdPerformanceDaily.day.between(first, last),
            )
        )
        seen: set[tuple[str, date]] = set()
        for r in rows:
            key = _entity_key(r)
            if key is None or (key, r.day) in seen:
                skipped += 1
                continue
            seen.add((key, r.day))
            group_id = groups.get(r.ad_group_external_id or r.entity_external_id or "")
            session.add(
                AdPerformanceDaily(
                    organization_id=account.organization_id,
                    ad_account_id=account.id,
                    level=level.value,
                    entity_key=key,
                    campaign_id=campaigns.get(r.campaign_external_id or "")
                    if level is not AdLevel.CAMPAIGN
                    else campaigns.get(r.entity_external_id or ""),
                    ad_group_id=group_id if level in (AdLevel.AD_GROUP, AdLevel.AD) else None,
                    ad_id=ads.get((group_id, r.entity_external_id or ""))
                    if level is AdLevel.AD and group_id is not None
                    else None,
                    day=r.day,
                    impressions=r.impressions,
                    clicks=r.clicks,
                    cost=r.cost,
                    conversions=r.conversions,
                    conversion_value=r.conversion_value,
                    currency=account.currency,
                    fetched_at=now,
                )
            )
            written += 1
        if level is AdLevel.ACCOUNT:  # Google sends no row for a day without activity
            day = first
            while day <= last:
                if (ACCOUNT_KEY, day) not in seen:
                    session.add(_zero_day(account, day, now))
                    written += 1
                day = _shift(day, 1)
    session.flush()
    if skipped:
        logger.warning(
            "ad_performance_rows_skipped",
            extra={"ad_account_id": str(account.id), "count": skipped},
        )
    return written


def _entity_key(record: AdPerformanceRecord) -> str | None:
    if record.level is AdLevel.ACCOUNT:
        return ACCOUNT_KEY
    if record.entity_external_id is None:
        return None
    if record.level is AdLevel.AD:  # an ad is identified within its ad group
        if record.ad_group_external_id is None:
            return None
        return f"{record.ad_group_external_id}~{record.entity_external_id}"
    return record.entity_external_id


def _zero_day(account: AdAccount, day: date, now: Any) -> AdPerformanceDaily:
    zero = Decimal(0)
    return AdPerformanceDaily(
        organization_id=account.organization_id,
        ad_account_id=account.id,
        level=AdLevel.ACCOUNT.value,
        entity_key=ACCOUNT_KEY,
        day=day,
        impressions=0,
        clicks=0,
        cost=zero,
        conversions=zero,
        conversion_value=zero,
        currency=account.currency,
        fetched_at=now,
    )


def _finish(rt: Runtime, ctx: _Context) -> None:
    now = rt.clock.now()
    with rt.db.transaction(org_id=ctx.org_id) as session:
        account = session.get(AdAccount, ctx.account_id)
        state = session.get(AdSyncState, ctx.account_id, with_for_update=True)
        assert account is not None
        assert state is not None
        if account.first_import_completed_at is None:
            account.first_import_completed_at = now
            record_audit(
                session,
                organization_id=ctx.org_id,
                actor=WORKER,
                action="ad_account.import_completed",
                resource_type="ad_account",
                resource_id=ctx.account_id,
            )
        account.status = "active"
        state.import_progress = 100
        state.import_job_id, state.import_cursor = None, None
        state.sync_mode = None
        state.last_nightly_at = now
        state.last_error_code = state.last_error_at = None
        state.updated_at = now


def _fail(rt: Runtime, ctx: _Context, code: str, *, health: bool) -> None:
    with rt.db.transaction(org_id=ctx.org_id) as session:
        account = session.get(AdAccount, ctx.account_id)
        state = session.get(AdSyncState, ctx.account_id, with_for_update=True)
        if account is None or state is None:
            return
        now = rt.clock.now()
        state.import_job_id, state.import_cursor, state.sync_mode = None, None, None
        state.last_error_code, state.last_error_at = code[:64], now
        if health:
            account.health_code, account.health_checked_at = code[:64], now
        if ctx.first_import:
            account.status = "error"
        record_audit(
            session,
            organization_id=ctx.org_id,
            actor=WORKER,
            action="ad_account.import_failed",
            resource_type="ad_account",
            resource_id=ctx.account_id,
            metadata={"error": code[:64]},
        )


# ------------------------------------------------------------------ applying structure
def apply_structure(
    session: Session,
    rt: Runtime,
    org_id: uuid.UUID,
    account_id: uuid.UUID,
    records: list[AdStructureRecord],
) -> dict[str, int]:
    """Insert or update every budget, campaign, ad group and ad (parents first). Children
    whose parent is unknown are skipped and counted."""
    account = session.get(AdAccount, account_id)
    assert account is not None
    now = rt.clock.now()
    counts = {"budgets": 0, "campaigns": 0, "ad_groups": 0, "ads": 0, "skipped": 0}

    budgets = _by_external(session, AdBudget, AdBudget.external_budget_id, account_id=account_id)
    for rb in _of(records, AdBudgetRecord):
        row = budgets.get(rb.external_id)
        if row is None:
            row = AdBudget(
                organization_id=org_id,
                ad_account_id=account_id,
                external_budget_id=rb.external_id,
                currency=account.currency,
            )
            session.add(row)
            budgets[rb.external_id] = row
        row.name, row.level, row.period = rb.name, rb.level, rb.period
        row.amount, row.shared, row.updated_at = rb.amount, rb.shared, now
        counts["budgets"] += 1
    session.flush()

    campaigns = _by_external(
        session, AdCampaign, AdCampaign.external_campaign_id, account_id=account_id
    )
    for rc in _of(records, AdCampaignRecord):
        campaign = campaigns.get(rc.external_id)
        if campaign is None:
            campaign = AdCampaign(
                organization_id=org_id,
                ad_account_id=account_id,
                external_campaign_id=rc.external_id,
            )
            session.add(campaign)
            campaigns[rc.external_id] = campaign
        budget = budgets.get(rc.budget_external_id) if rc.budget_external_id else None
        campaign.name, campaign.status = rc.name, rc.status.value
        campaign.platform_type, campaign.bidding_strategy_type = (
            rc.platform_type,
            rc.bidding_strategy_type,
        )
        campaign.start_date, campaign.end_date = rc.start_date, rc.end_date
        campaign.budget_id = budget.id if budget is not None else None
        campaign.provider_extensions = dict(rc.extensions) if rc.extensions else None
        campaign.updated_at = now
        counts["campaigns"] += 1
    session.flush()

    campaign_ids = [c.id for c in campaigns.values()]
    groups: dict[tuple[uuid.UUID, str], AdGroup] = {
        (g.campaign_id, g.external_ad_group_id): g
        for g in session.execute(
            select(AdGroup).where(AdGroup.campaign_id.in_(campaign_ids))
        ).scalars()
    }
    by_group_external: dict[str, AdGroup] = {g.external_ad_group_id: g for g in groups.values()}
    for rg in _of(records, AdGroupRecord):
        parent = campaigns.get(rg.campaign_external_id)
        if parent is None:
            counts["skipped"] += 1
            continue
        group = groups.get((parent.id, rg.external_id))
        if group is None:
            group = AdGroup(
                organization_id=org_id, campaign_id=parent.id, external_ad_group_id=rg.external_id
            )
            session.add(group)
            groups[(parent.id, rg.external_id)] = group
        budget = budgets.get(rg.budget_external_id) if rg.budget_external_id else None
        group.name, group.status, group.platform_type = rg.name, rg.status.value, rg.platform_type
        group.budget_id = budget.id if budget is not None else None
        group.provider_extensions = dict(rg.extensions) if rg.extensions else None
        group.updated_at = now
        by_group_external[rg.external_id] = group
        counts["ad_groups"] += 1
    session.flush()

    group_ids = [g.id for g in by_group_external.values()]
    ads: dict[tuple[uuid.UUID, str], Ad] = {
        (a.ad_group_id, a.external_ad_id): a
        for a in session.execute(select(Ad).where(Ad.ad_group_id.in_(group_ids))).scalars()
    }
    for ra in _of(records, AdRecord):
        parent_group = by_group_external.get(ra.ad_group_external_id)
        if parent_group is None:
            counts["skipped"] += 1
            continue
        item = ads.get((parent_group.id, ra.external_id))
        if item is None:
            item = Ad(
                organization_id=org_id, ad_group_id=parent_group.id, external_ad_id=ra.external_id
            )
            session.add(item)
            ads[(parent_group.id, ra.external_id)] = item
        item.name, item.status, item.platform_type = ra.name, ra.status.value, ra.platform_type
        item.provider_extensions = dict(ra.extensions) if ra.extensions else None
        item.updated_at = now
        counts["ads"] += 1
    session.flush()
    if counts["skipped"]:
        logger.warning(
            "ad_structure_rows_skipped",
            extra={"ad_account_id": str(account_id), "count": counts["skipped"]},
        )
    return counts


def _of[T](records: list[AdStructureRecord], kind: type[T]) -> list[T]:
    return [r for r in records if isinstance(r, kind)]


def _by_external(
    session: Session, model: Any, column: Any, *, account_id: uuid.UUID
) -> dict[str, Any]:
    return {
        getattr(row, column.key): row
        for row in session.execute(select(model).where(model.ad_account_id == account_id)).scalars()
    }
