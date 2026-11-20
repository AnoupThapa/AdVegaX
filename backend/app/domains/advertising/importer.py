"""Importing and syncing linked ad accounts (Phase 3, tasks 3-05 … 3-07; PHASE_03_PLAN §9).

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
Removed campaigns, ad groups and ads are kept (status ``removed``) so their history stays
readable; items the platform stops listing are left as they are, never deleted on absence.

Modes (``ad_sync_state.sync_mode``, 3-07): ``initial`` (structure + 13 months in monthly
slices); ``quick`` every 3 hours (structure + today and yesterday); ``nightly`` (the last 30
days) and ``weekly`` (the last 90 days), each re-read in one step. "Sync now" is a nightly
re-read with the structure. Every step first reserves its operations in the platform
allowance shared by all customers (``quota``); a step that does not fit waits and retries,
nightly and weekly re-reads waiting first.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.core.security.throttle import Limit
from app.domains.advertising.models import (
    Ad,
    AdAccount,
    AdBudget,
    AdCampaign,
    AdGroup,
    AdPerformanceDaily,
    AdSyncState,
)
from app.domains.advertising.quota import SharedQuota
from app.domains.audit.service import Actor, record_audit
from app.domains.billing.entitlements import is_read_only
from app.domains.integrations.jobs import call_provider
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.integrations.tokens import AccountBusy, account_lock, usable_secrets
from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError, create_job
from app.providers.base.errors import (
    AccountBusyError,
    PlatformQuotaError,
    ProviderError,
    ResourceUnavailableError,
)
from app.providers.base.interfaces import AdvertisingProvider, PlatformProvider
from app.providers.base.registry import UnknownProvider
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
QUOTA_WAITING = "quota_waiting"  # last_error_code while a step waits for the allowance
KEPT_HEALTH = frozenset({"account_details_changed"})  # re-checked by each structure read
HOUR = 3600


class SyncMode(StrEnum):
    INITIAL = "initial"
    QUICK = "quick"
    NIGHTLY = "nightly"
    WEEKLY = "weekly"
    # Phase 7 (Q-7-4): an account of a platform that reports funnel actions, imported before
    # they were read, is read once more over its whole history (figures only, sliced by month).
    REREAD = "reread"


class AdSyncInProgress(Conflict):
    code = "SYNC_IN_PROGRESS"
    message = "This ad account is already being synchronized."


class AdAccountNotSyncing(Conflict):
    code = "AD_ACCOUNT_NOT_SYNCING"
    message = "This ad account is not linked to an active connection."


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
    """Linking: the first import, or (an imported account linked again) a nightly-style
    re-read with the structure."""
    if account.first_import_completed_at is None:
        return start_sync(session, rt, account, SyncMode.INITIAL, requested_by=requested_by)
    return start_sync(
        session, rt, account, SyncMode.NIGHTLY, requested_by=requested_by, structure=True
    )


def start_sync(
    session: Session,
    rt: Runtime,
    account: AdAccount,
    mode: SyncMode,
    *,
    requested_by: uuid.UUID | None = None,
    structure: bool | None = None,
) -> uuid.UUID:
    """(Re)start the account's chain in ``mode``. The structure is read first for the first
    import and the 3-hour run (and "Sync now"); nightly and weekly runs read figures only."""
    state = session.get(AdSyncState, account.id, with_for_update=True)
    if state is None:
        state = AdSyncState(ad_account_id=account.id, organization_id=account.organization_id)
        session.add(state)
    if structure is None:
        structure = mode in (SyncMode.INITIAL, SyncMode.QUICK)
    if mode is SyncMode.INITIAL:
        account.status = "importing"
        state.import_progress = 0
    state.sync_mode = mode.value
    state.sync_started_at = rt.clock.now()
    state.import_cursor = STEP_STRUCTURE if structure else _cursor(*window(rt, account, mode))
    state.last_error_code = state.last_error_at = None
    job = _schedule(session, rt, account, state, requested_by=requested_by)
    if mode is SyncMode.INITIAL or requested_by is not None:  # scheduled runs: logs only
        record_audit(
            session,
            organization_id=account.organization_id,
            actor=Actor.user(requested_by) if requested_by else WORKER,
            action="ad_account.import_started"
            if mode is SyncMode.INITIAL
            else "ad_account.sync_started",
            resource_type="ad_account",
            resource_id=account.id,
            metadata={"job_id": str(job), "mode": mode.value},
        )
    return job


def window(rt: Runtime, account: AdAccount, mode: SyncMode) -> tuple[date, date]:
    """The days a run of ``mode`` reads, in the account's time zone, never before its
    history start."""
    today = local_today(rt, account.timezone)
    start = history_start(rt, account)
    days = {
        SyncMode.INITIAL: None,
        SyncMode.REREAD: None,
        SyncMode.QUICK: rt.settings.ADS_QUICK_WINDOW.days,
        SyncMode.NIGHTLY: rt.settings.ADS_NIGHTLY_WINDOW.days,
        SyncMode.WEEKLY: rt.settings.ADS_WEEKLY_WINDOW.days,
    }[mode]
    first = start if days is None else max(start, _shift(today, 1 - max(1, days)))
    return min(first, today), today


def chain_running(rt: Runtime, state: AdSyncState) -> bool:
    """A chain is running unless none was started or it has been silent too long."""
    if state.import_job_id is None:
        return False
    return state.updated_at > rt.clock.now() - rt.settings.ADS_CHAIN_STALE_AFTER


def _schedule(
    session: Session,
    rt: Runtime,
    account: AdAccount,
    state: AdSyncState,
    *,
    requested_by: uuid.UUID | None = None,
    delay_seconds: int = 0,
) -> uuid.UUID:
    job = create_job(
        session,
        rt,
        organization_id=account.organization_id,
        job_type=JOB_AD_IMPORT_STEP,
        subject_type="ad_account",
        subject_id=account.id,
        requested_by=requested_by,
        delay_seconds=delay_seconds,
    )
    if delay_seconds > 0:  # durable: an early or re-sent message finds the job not yet due
        job.next_attempt_at = func.now() + timedelta(seconds=delay_seconds)
    state.import_job_id = job.id
    state.updated_at = rt.clock.now()
    return job.id


# ------------------------------------------------------------------ schedule and "Sync now"
def due_mode(
    rt: Runtime, state: AdSyncState | None, *, defer_rereads: bool = False
) -> SyncMode | None:
    """The run an imported account needs now, the longest first: weekly, nightly, then the
    3-hour run. Nightly and weekly wait while the shared allowance is mostly used."""
    now = rt.clock.now()
    settings = rt.settings

    def due(last: Any, interval: Any) -> bool:
        return last is None or last <= now - interval

    last_weekly = state.last_weekly_at if state else None
    last_nightly = state.last_nightly_at if state else None
    last_quick = state.last_quick_at if state else None
    if not defer_rereads:
        if due(last_weekly, settings.ADS_WEEKLY_INTERVAL):
            return SyncMode.WEEKLY
        if due(last_nightly, settings.ADS_NIGHTLY_INTERVAL):
            return SyncMode.NIGHTLY
    if due(last_quick, settings.ADS_QUICK_INTERVAL):
        return SyncMode.QUICK
    return None


def _syncable(session: Session, account: AdAccount) -> bool:
    """Linked, through an active connection."""
    row = session.execute(
        select(ExternalConnection.status)
        .join(ExternalResource, ExternalResource.connection_id == ExternalConnection.id)
        .join(
            OrganizationResourceLink,
            OrganizationResourceLink.external_resource_id == ExternalResource.id,
        )
        .where(
            ExternalResource.id == account.external_resource_id,
            OrganizationResourceLink.status == "active",
        )
    ).first()
    return row is not None and row[0] == "active"


def enqueue_ad_syncs(rt: Runtime) -> int:
    """Start the run each imported ad account is due for (every tick of the scheduler).
    Accounts come due at their own times (3 hours after their last run), so runs spread
    over the day instead of starting together. Returns how many were started.

    The account list comes from a narrow system-role read of ``ad_accounts`` (0013 grant);
    everything else runs under each account's tenant context."""
    with rt.db.transaction(system=True) as session:
        accounts = session.execute(
            select(AdAccount.id, AdAccount.organization_id, AdAccount.provider).where(
                AdAccount.first_import_completed_at.is_not(None)
            )
        ).all()
    defer: dict[str, bool | None] = {}  # per platform; None = not available here
    funnel: dict[str, bool] = {}  # per platform: does it report funnel actions (Phase 7)?
    started = 0
    for account_id, org_id, provider_code in accounts:
        if provider_code not in defer:
            defer[provider_code] = _defer_rereads(rt, provider_code)
            funnel[provider_code] = _reports_funnel(rt, provider_code)
        if defer[provider_code] is None:
            continue
        with rt.db.transaction(org_id=org_id) as session:
            account = session.get(AdAccount, account_id)
            state = session.get(AdSyncState, account_id, with_for_update=True)
            if account is None or (state is not None and chain_running(rt, state)):
                continue
            if not _syncable(session, account) or is_read_only(rt, session, org_id):
                continue
            mode = due_mode(rt, state, defer_rereads=bool(defer[provider_code]))
            if mode is None and account.funnel_reread_at is None:
                if not funnel[provider_code]:
                    account.funnel_reread_at = rt.clock.now()  # nothing more to read
                elif not defer[provider_code]:
                    mode = SyncMode.REREAD  # once, when nothing more urgent is due (Q-7-4)
            if mode is None:
                continue
            start_sync(session, rt, account, mode)
            started += 1
    if started:
        logger.info("ad_syncs_started", extra={"count": started})
    return started


def _reports_funnel(rt: Runtime, provider_code: str) -> bool:
    """Whether the platform reports funnel actions (an optional provider attribute)."""
    try:
        return getattr(rt.providers.get(provider_code), "funnel_actions", False) is True
    except UnknownProvider:
        return False


def _defer_rereads(rt: Runtime, provider_code: str) -> bool | None:
    """Whether nightly and weekly re-reads wait (the shared allowance is mostly used);
    None when the platform is not available in this deployment."""
    try:
        provider = advertising_provider(rt.providers.get(provider_code))
    except UnknownProvider:
        return None
    if provider is None:
        return None
    return quota_share_used(rt, provider) >= rt.settings.ADS_QUOTA_DEFER_SHARE


def request_sync(
    session: Session, rt: Runtime, account: AdAccount, *, requested_by: uuid.UUID
) -> tuple[uuid.UUID, SyncMode]:
    """ "Sync now": the structure and the last 30 days (or the first import again, when it
    did not finish). Limited per account, not per person."""
    if not _syncable(session, account):
        raise AdAccountNotSyncing()
    state = session.get(AdSyncState, account.id, with_for_update=True)
    if state is not None and chain_running(rt, state):
        raise AdSyncInProgress()
    rt.throttler.hit(
        Limit("ad_account_resync", rt.settings.THROTTLE_AD_ACCOUNT_RESYNC_PER_HOUR, HOUR),
        str(account.id),
    )
    if account.first_import_completed_at is None:
        return start_import(session, rt, account, requested_by=requested_by), SyncMode.INITIAL
    job = start_sync(
        session, rt, account, SyncMode.NIGHTLY, requested_by=requested_by, structure=True
    )
    return job, SyncMode.NIGHTLY


# ------------------------------------------------------------------ the step
@dataclass(frozen=True)
class _Context:
    org_id: uuid.UUID
    account_id: uuid.UUID
    connection_id: uuid.UUID
    ref: AdAccountRef
    step: str
    first_import: bool
    mode: SyncMode
    requested_by: uuid.UUID | None
    platform: str


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
                # A person's "Sync now" stays theirs through the chain (it never waits first).
                _schedule(session, rt, account, state, requested_by=job.requested_by_user_id)


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
                mode=_mode(state.sync_mode, account),
                requested_by=job.requested_by_user_id,
                platform=connection.provider,
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
        wait = _quota_wait(rt, ctx, provider)
        if wait is not None:
            _wait(rt, ctx, job, wait)
            return False
        if ctx.step == STEP_STRUCTURE:
            return _structure(rt, ctx, provider)
        if (span := performance_cursor(ctx.step)) is not None:
            return _performance(rt, ctx, provider, *span)
        _finish(rt, ctx)
        return False
    except ResourceUnavailableError as exc:
        _fail(rt, ctx, exc.code, health=True)
        return False
    except AccountBusyError as exc:  # the platform asks this one account to wait (Meta)
        delay = exc.retry_after_seconds or rt.settings.ADS_ACCOUNT_BUSY_WAIT.total_seconds()
        logger.info(
            "ad_account_busy_waiting",
            extra={"ad_account_id": str(ctx.account_id), "retry_after_seconds": int(delay)},
        )
        _wait(rt, ctx, job, delay)
        return False
    except PlatformQuotaError as exc:  # the platform says the shared allowance is used up
        delay = exc.retry_after_seconds or rt.settings.ADS_QUOTA_WAIT.total_seconds()
        SharedQuota(rt.redis, rt.clock).block(ctx.platform, delay)
        logger.warning(
            "ad_platform_quota_exhausted",
            extra={"provider": ctx.platform, "retry_after_seconds": int(delay)},
        )
        _wait(rt, ctx, job, delay)
        return False
    except ProviderError as exc:
        if not exc.retryable or job.attempts >= job.max_attempts:
            _fail(rt, ctx, exc.code, health=False)
        raise


def _mode(value: str | None, account: AdAccount) -> SyncMode:
    if value in {m.value for m in SyncMode}:
        return SyncMode(value)
    initial = account.first_import_completed_at is None
    return SyncMode.INITIAL if initial else SyncMode.NIGHTLY


def _call(rt: Runtime, ctx: _Context, provider: AdvertisingProvider, fn: Any) -> Any:
    return call_provider(rt, provider, ctx.org_id, ctx.connection_id, fn)


# ------------------------------------------------------------------ shared allowance
def _cost(ctx: _Context, provider: AdvertisingProvider) -> int:
    if ctx.step == STEP_STRUCTURE:
        return int(getattr(provider, "structure_operations", 0))
    if performance_cursor(ctx.step) is not None:
        return int(getattr(provider, "level_operations", 0)) * len(AdLevel)
    return 0


def _quota_wait(rt: Runtime, ctx: _Context, provider: AdvertisingProvider) -> float | None:
    """Reserve this step's operations; the seconds to wait when they do not fit, else None.
    Nightly and weekly re-reads stop at a share of the allowance, so first imports, 3-hour
    runs and a person's "Sync now" keep the rest."""
    if ctx.step != STEP_STRUCTURE and performance_cursor(ctx.step) is None:
        return None  # the last step calls nobody
    quota = SharedQuota(rt.redis, rt.clock)
    blocked = quota.blocked_for(ctx.platform)
    if blocked > 0:  # the platform said every AdVegaX account must wait (Google or Meta)
        return blocked
    cost = _cost(ctx, provider)
    if cost == 0:
        return None
    limit = getattr(provider, "shared_daily_operations", None)
    if not isinstance(limit, int) or limit <= 0:
        return None
    deferrable = (
        ctx.mode in (SyncMode.NIGHTLY, SyncMode.WEEKLY, SyncMode.REREAD)
        and ctx.requested_by is None
    )
    ceiling = int(limit * rt.settings.ADS_QUOTA_DEFER_SHARE) if deferrable else limit
    window_seconds = rt.settings.ADS_QUOTA_WINDOW.total_seconds()
    if quota.reserve(ctx.platform, cost, ceiling=ceiling, window_seconds=window_seconds):
        return None
    logger.info(
        "ad_sync_waiting_for_allowance",
        extra={"ad_account_id": str(ctx.account_id), "mode": ctx.mode.value},
    )
    return rt.settings.ADS_QUOTA_WAIT.total_seconds()


def quota_share_used(rt: Runtime, provider: AdvertisingProvider) -> float:
    """How much of the shared allowance the last window used (0 … 1; 0 when none)."""
    limit = getattr(provider, "shared_daily_operations", None)
    if not isinstance(limit, int) or limit <= 0:
        return 0.0
    used = SharedQuota(rt.redis, rt.clock).used(
        provider.code, window_seconds=rt.settings.ADS_QUOTA_WINDOW.total_seconds()
    )
    return used / limit


def _wait(rt: Runtime, ctx: _Context, job: ClaimedJob, seconds: float) -> None:
    """Hold the chain: the same step runs again later, as a new job (no attempt is used)."""
    with rt.db.transaction(org_id=ctx.org_id) as session:
        account = session.get(AdAccount, ctx.account_id)
        state = session.get(AdSyncState, ctx.account_id, with_for_update=True)
        if account is None or state is None or state.import_job_id != job.id:
            return
        _schedule(
            session,
            rt,
            account,
            state,
            requested_by=ctx.requested_by,
            delay_seconds=max(1, int(seconds)),
        )
        state.last_error_code, state.last_error_at = QUOTA_WAITING, rt.clock.now()


def _clear_waiting(state: AdSyncState) -> None:
    if state.last_error_code == QUOTA_WAITING:
        state.last_error_code = state.last_error_at = None


def _structure(rt: Runtime, ctx: _Context, provider: AdvertisingProvider) -> bool:
    secrets = usable_secrets(rt, ctx.org_id, ctx.connection_id)
    state = _call(rt, ctx, provider, lambda: provider.read_account(secrets, ctx.ref))
    with rt.db.transaction(org_id=ctx.org_id) as session:
        account = session.get(AdAccount, ctx.account_id)
        assert account is not None
        account.name = state.name or account.name
        account.platform_status = state.platform_status
        account.health_checked_at = rt.clock.now()
        # The account answered: earlier access problems are over. Currency and time zone are
        # fixed for the life of a Google Ads account; a change would make stored figures
        # inconsistent, so it is recorded, never applied silently.
        if state.platform_status != "active":
            account.health_code = state.unavailable_reason or "account_not_enabled"
        elif (state.currency, state.timezone) != (account.currency, account.timezone):
            account.health_code = "account_details_changed"
        else:
            account.health_code = None
    if state.platform_status != "active":
        _fail(rt, ctx, state.unavailable_reason or "account_not_enabled", health=True)
        return False
    records = _call(rt, ctx, provider, lambda: list(provider.read_structure(secrets, ctx.ref)))
    with rt.db.transaction(org_id=ctx.org_id) as session:
        counts = apply_structure(session, rt, ctx.org_id, ctx.account_id, records)
        sync = session.get(AdSyncState, ctx.account_id, with_for_update=True)
        assert sync is not None
        account = session.get(AdAccount, ctx.account_id)
        assert account is not None
        sync.import_cursor = _cursor(*window(rt, account, ctx.mode))
        _clear_waiting(sync)
        sync.updated_at = rt.clock.now()
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
    # The first import and the one-time re-read read calendar months; a regular re-read (2,
    # 30 or 90 days) is one step.
    whole = ctx.mode in (SyncMode.INITIAL, SyncMode.REREAD)
    end = month_slice(first, last) if whole else last
    secrets = usable_secrets(rt, ctx.org_id, ctx.connection_id)
    records: dict[AdLevel, list[AdPerformanceRecord]] = {}
    for level in AdLevel:
        records[level] = _call(
            rt,
            ctx,
            provider,
            lambda level=level: list(
                provider.read_performance(secrets, ctx.ref, level, first, end)
            ),
        )
    with rt.db.transaction(org_id=ctx.org_id) as session:
        account = session.get(AdAccount, ctx.account_id)
        sync = session.get(AdSyncState, ctx.account_id, with_for_update=True)
        assert account is not None
        assert sync is not None
        written = apply_performance(
            session,
            rt,
            account,
            first,
            end,
            records,
            funnel_actions=getattr(provider, "funnel_actions", False) is True,
        )
        more = end < last
        sync.import_cursor = _cursor(_shift(end, 1), last) if more else STEP_DONE
        _clear_waiting(sync)
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
    *,
    funnel_actions: bool = False,
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
                    landing_page_views=r.landing_page_views,
                    content_views=r.content_views,
                    adds_to_cart=r.adds_to_cart,
                    checkouts_initiated=r.checkouts_initiated,
                    currency=account.currency,
                    fetched_at=now,
                )
            )
            written += 1
        if level is AdLevel.ACCOUNT:  # Google sends no row for a day without activity
            day = first
            while day <= last:
                if (ACCOUNT_KEY, day) not in seen:
                    session.add(_zero_day(account, day, now, funnel_actions))
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


def _zero_day(
    account: AdAccount, day: date, now: Any, funnel_actions: bool = False
) -> AdPerformanceDaily:
    """A day the platform sent nothing for: real zeros, and zero funnel actions only for a
    platform that reports them (otherwise they stay "not provided")."""
    zero = Decimal(0)
    funnel = zero if funnel_actions else None
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
        landing_page_views=funnel,
        content_views=funnel,
        adds_to_cart=funnel,
        checkouts_initiated=funnel,
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
        if account.health_code not in KEPT_HEALTH:  # the run reached the account
            account.health_code, account.health_checked_at = None, now
        state.import_progress = 100
        # What this run covered: the first import everything; a 3-hour run the recent days
        # and structure; nightly (incl. "Sync now") 30 days; weekly 90 days.
        if ctx.mode in (SyncMode.INITIAL, SyncMode.REREAD):
            account.funnel_reread_at = now  # read with the funnel actions (Q-7-4)
        if ctx.mode is SyncMode.INITIAL:
            state.last_quick_at = state.last_nightly_at = state.last_weekly_at = now
        elif ctx.mode is SyncMode.QUICK:
            state.last_quick_at = now
        elif ctx.mode is SyncMode.NIGHTLY:
            state.last_nightly_at = now
        else:
            state.last_weekly_at = state.last_nightly_at = now
        state.import_job_id, state.import_cursor = None, None
        state.sync_mode = None
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
