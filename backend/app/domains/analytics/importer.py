"""Importing linked analytics properties (Phase 5, task 5-05; PHASE_05_PLAN §9).

Platform-neutral: the core asks an ``AnalyticsProvider`` for the property's state and its daily
figures in three views (total, channel, source / medium / campaign) and stores them in the
analytics tables. As for ad accounts, the work is a **chain of short jobs**
(``analytics.import_step``), one step each, under a per-property lock;
``analytics_sync_state.import_job_id`` names the only step allowed to continue, so a duplicated
job message stops at once.

Steps (``analytics_sync_state.import_cursor``): ``property`` (name, currency, time zone,
deleted or not) → ``days:<first>:<last>`` (the first import reads one calendar month a step:
13 months ≈ 14 steps, each one platform call holding the three views) → ``done``. Each slice
**replaces** the stored figures of its days in every view, so late data and attribution changes
never leave stale numbers. The total view gets real zeros for days the platform reports
nothing (A10: zero only where the platform says zero); the other views have no "nothing" row.

Users are distinct counts per day and view: they are **never added up** — not across days, not
across views, and not when the source view's rare values are combined into "(other)" (their
users are left unknown, Q-5-5).

The 3-hour, nightly (14 days) and weekly (90 days) re-reads, quota pacing and health are
task 5-06; the windows they use are defined here.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.domains.analytics.models import (
    TOTAL_KEY,
    AnalyticsDaily,
    AnalyticsProperty,
    AnalyticsSyncState,
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
from app.providers.base.errors import AccountBusyError, ProviderError, ResourceUnavailableError
from app.providers.base.interfaces import AnalyticsProvider, PlatformProvider
from app.providers.base.types import (
    AnalyticsBreakdown,
    AnalyticsDailyRecord,
    AnalyticsPropertyRef,
    AnalyticsQuality,
    ProviderCategory,
    ResourceKind,
)
from app.runtime import Runtime

logger = logging.getLogger("advegax.analytics.importer")

JOB_ANALYTICS_IMPORT_STEP = "analytics.import_step"
WORKER = Actor("worker", None)
IMPORT_LOCK_TTL_SECONDS = 15 * 60
STEP_PROPERTY = "property"
STEP_DAYS = "days"
STEP_DONE = "done"
WAITING = "quota_waiting"  # last_error_code while a step waits for the property's allowance
OTHER = "(other)"
NOT_SET = "(not set)"


class SyncMode(StrEnum):
    INITIAL = "initial"
    QUICK = "quick"
    NIGHTLY = "nightly"
    WEEKLY = "weekly"


def analytics_provider(provider: PlatformProvider) -> AnalyticsProvider | None:
    if provider.category is not ProviderCategory.ANALYTICS:
        return None
    if not all(hasattr(provider, m) for m in ("read_property", "read_daily")):
        return None
    return cast(AnalyticsProvider, provider)


def local_today(rt: Runtime, timezone: str) -> date:
    return rt.clock.now().astimezone(ZoneInfo(timezone)).date()


def _shift(day: date, days: int) -> date:
    return date.fromordinal(day.toordinal() + days)


# ------------------------------------------------------------------ linking
def on_property_linked(
    session: Session,
    rt: Runtime,
    *,
    resource: ExternalResource,
    connection: ExternalConnection,
    user_id: uuid.UUID | None,
) -> AnalyticsProperty | None:
    """Called inside the link transaction: create the property (first link) and start its
    import. Returns ``None`` for anything that is not an analytics property."""
    provider = analytics_provider(rt.providers.get(connection.provider))
    if provider is None or resource.kind != ResourceKind.ANALYTICS_PROPERTY.value:
        return None
    if resource.currency is None or resource.timezone is None:
        return None  # linking is refused before this for such properties (5-04)
    prop = session.execute(
        select(AnalyticsProperty).where(AnalyticsProperty.external_resource_id == resource.id)
    ).scalar_one_or_none()
    if prop is None:
        today = local_today(rt, resource.timezone)
        prop = AnalyticsProperty(
            organization_id=resource.organization_id,
            external_resource_id=resource.id,
            provider=connection.provider,
            external_property_id=resource.external_id,
            name=resource.display_name,
            account_name=resource.group_path,
            currency=resource.currency,
            timezone=resource.timezone,
            status="importing",
            platform_status="active",
            history_from=_shift(today, -rt.settings.ANALYTICS_HISTORY_WINDOW.days),
        )
        session.add(prop)
        session.flush()
        session.add(AnalyticsSyncState(property_id=prop.id, organization_id=prop.organization_id))
        session.flush()
    start_import(session, rt, prop, requested_by=user_id)
    return prop


def start_import(
    session: Session, rt: Runtime, prop: AnalyticsProperty, *, requested_by: uuid.UUID | None
) -> uuid.UUID:
    """The first import, or (a property imported before and linked again) a nightly
    re-read."""
    mode = SyncMode.INITIAL if prop.first_import_completed_at is None else SyncMode.NIGHTLY
    return start_sync(session, rt, prop, mode, requested_by=requested_by)


def start_sync(
    session: Session,
    rt: Runtime,
    prop: AnalyticsProperty,
    mode: SyncMode,
    *,
    requested_by: uuid.UUID | None = None,
) -> uuid.UUID:
    """(Re)start the property's chain in ``mode``; every run reads the property first."""
    state = session.get(AnalyticsSyncState, prop.id, with_for_update=True)
    if state is None:
        state = AnalyticsSyncState(property_id=prop.id, organization_id=prop.organization_id)
        session.add(state)
    if mode is SyncMode.INITIAL:
        prop.status = "importing"
        state.import_progress = 0
    state.sync_mode = mode.value
    state.sync_started_at = rt.clock.now()
    state.import_cursor = STEP_PROPERTY
    state.last_error_code = state.last_error_at = None
    job = _schedule(session, rt, prop, state, requested_by=requested_by)
    if mode is SyncMode.INITIAL or requested_by is not None:  # scheduled runs: logs only
        record_audit(
            session,
            organization_id=prop.organization_id,
            actor=Actor.user(requested_by) if requested_by else WORKER,
            action="analytics_property.import_started"
            if mode is SyncMode.INITIAL
            else "analytics_property.sync_started",
            resource_type="analytics_property",
            resource_id=prop.id,
            metadata={"job_id": str(job), "mode": mode.value},
        )
    return job


def history_start(rt: Runtime, prop: AnalyticsProperty) -> date:
    if prop.history_from is not None:
        return prop.history_from
    return _shift(local_today(rt, prop.timezone), -rt.settings.ANALYTICS_HISTORY_WINDOW.days)


def window(rt: Runtime, prop: AnalyticsProperty, mode: SyncMode) -> tuple[date, date]:
    """The days a run of ``mode`` reads, in the property's time zone, never before its
    history start."""
    today = local_today(rt, prop.timezone)
    start = history_start(rt, prop)
    days = {
        SyncMode.INITIAL: None,
        SyncMode.QUICK: rt.settings.ANALYTICS_QUICK_WINDOW.days,
        SyncMode.NIGHTLY: rt.settings.ANALYTICS_NIGHTLY_WINDOW.days,
        SyncMode.WEEKLY: rt.settings.ANALYTICS_WEEKLY_WINDOW.days,
    }[mode]
    first = start if days is None else max(start, _shift(today, 1 - max(1, days)))
    return min(first, today), today


def chain_running(rt: Runtime, state: AnalyticsSyncState) -> bool:
    if state.import_job_id is None:
        return False
    return state.updated_at > rt.clock.now() - rt.settings.ANALYTICS_CHAIN_STALE_AFTER


def _schedule(
    session: Session,
    rt: Runtime,
    prop: AnalyticsProperty,
    state: AnalyticsSyncState,
    *,
    requested_by: uuid.UUID | None = None,
    delay_seconds: int = 0,
) -> uuid.UUID:
    job = create_job(
        session,
        rt,
        organization_id=prop.organization_id,
        job_type=JOB_ANALYTICS_IMPORT_STEP,
        subject_type="analytics_property",
        subject_id=prop.id,
        requested_by=requested_by,
        delay_seconds=delay_seconds,
    )
    if delay_seconds > 0:  # durable: an early or re-sent message finds the job not yet due
        job.next_attempt_at = func.now() + timedelta(seconds=delay_seconds)
    state.import_job_id = job.id
    state.updated_at = rt.clock.now()
    return job.id


# ------------------------------------------------------------------ the step
@dataclass(frozen=True)
class _Context:
    org_id: uuid.UUID
    property_id: uuid.UUID
    connection_id: uuid.UUID
    ref: AnalyticsPropertyRef
    step: str
    first_import: bool
    mode: SyncMode
    requested_by: uuid.UUID | None


def import_step(rt: Runtime, job: ClaimedJob) -> None:
    if job.organization_id is None or job.subject_id is None:
        raise JobSubjectGoneError()
    org_id, property_id = job.organization_id, uuid.UUID(job.subject_id)
    try:
        with account_lock(
            rt.redis,
            f"analytics-import-lock:{property_id}",
            wait_seconds=0,
            ttl_seconds=IMPORT_LOCK_TTL_SECONDS,
        ):
            again = _step(rt, job, org_id, property_id)
    except AccountBusy:
        logger.info("analytics_import_step_busy", extra={"property_id": str(property_id)})
        return
    if again:
        with rt.db.transaction(org_id=org_id) as session:
            prop = session.get(AnalyticsProperty, property_id)
            state = session.get(AnalyticsSyncState, property_id, with_for_update=True)
            if prop is not None and state is not None and state.import_job_id == job.id:
                _schedule(session, rt, prop, state, requested_by=job.requested_by_user_id)


def _load(
    rt: Runtime, job: ClaimedJob, org_id: uuid.UUID, property_id: uuid.UUID
) -> tuple[_Context | None, AnalyticsProvider | None]:
    with rt.db.transaction(org_id=org_id) as session:
        row = session.execute(
            select(AnalyticsProperty, AnalyticsSyncState, ExternalResource, ExternalConnection)
            .join(AnalyticsSyncState, AnalyticsSyncState.property_id == AnalyticsProperty.id)
            .join(ExternalResource, ExternalResource.id == AnalyticsProperty.external_resource_id)
            .join(ExternalConnection, ExternalConnection.id == ExternalResource.connection_id)
            .where(AnalyticsProperty.id == property_id, AnalyticsProperty.organization_id == org_id)
        ).one_or_none()
        if row is None:
            raise JobSubjectGoneError()
        prop, state, resource, connection = row
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
        provider = analytics_provider(rt.providers.get(connection.provider))
        if provider is None:
            raise JobSubjectGoneError()
        return (
            _Context(
                org_id=org_id,
                property_id=prop.id,
                connection_id=connection.id,
                ref=AnalyticsPropertyRef(prop.external_property_id, resource.access_hint),
                step=state.import_cursor or STEP_PROPERTY,
                first_import=prop.first_import_completed_at is None,
                mode=_mode(state.sync_mode, prop),
                requested_by=job.requested_by_user_id,
            ),
            provider,
        )


def _mode(value: str | None, prop: AnalyticsProperty) -> SyncMode:
    if value in {m.value for m in SyncMode}:
        return SyncMode(value)
    return SyncMode.INITIAL if prop.first_import_completed_at is None else SyncMode.NIGHTLY


def _step(rt: Runtime, job: ClaimedJob, org_id: uuid.UUID, property_id: uuid.UUID) -> bool:
    """Run one step; ``True`` when another step follows. Temporary platform errors propagate
    (the job framework retries with back-off); an unusable property or a permanent error (or
    the last retry) ends the chain with a plain code on the property."""
    ctx, provider = _load(rt, job, org_id, property_id)
    if ctx is None or provider is None:
        return False
    try:
        if ctx.step == STEP_PROPERTY:
            return _property(rt, ctx, provider)
        if (span := days_cursor(ctx.step)) is not None:
            return _days(rt, ctx, provider, *span)
        _finish(rt, ctx)
        return False
    except ResourceUnavailableError as exc:
        _fail(rt, ctx, exc.code, health=True)
        return False
    except AccountBusyError as exc:  # the property's quota is used up: only it waits
        delay = exc.retry_after_seconds or rt.settings.ANALYTICS_PROPERTY_BUSY_WAIT.total_seconds()
        logger.info(
            "analytics_property_busy_waiting",
            extra={"property_id": str(ctx.property_id), "retry_after_seconds": int(delay)},
        )
        _wait(rt, ctx, job, delay)
        return False
    except ProviderError as exc:
        if not exc.retryable or job.attempts >= job.max_attempts:
            _fail(rt, ctx, exc.code, health=False)
        raise


def _call(rt: Runtime, ctx: _Context, provider: AnalyticsProvider, fn: Any) -> Any:
    return call_provider(rt, provider, ctx.org_id, ctx.connection_id, fn)


def _wait(rt: Runtime, ctx: _Context, job: ClaimedJob, seconds: float) -> None:
    """Hold the chain: the same step runs again later, as a new job (no attempt is used)."""
    with rt.db.transaction(org_id=ctx.org_id) as session:
        prop = session.get(AnalyticsProperty, ctx.property_id)
        state = session.get(AnalyticsSyncState, ctx.property_id, with_for_update=True)
        if prop is None or state is None or state.import_job_id != job.id:
            return
        _schedule(
            session,
            rt,
            prop,
            state,
            requested_by=ctx.requested_by,
            delay_seconds=max(1, int(seconds)),
        )
        state.last_error_code, state.last_error_at = WAITING, rt.clock.now()


def _clear_waiting(state: AnalyticsSyncState) -> None:
    if state.last_error_code == WAITING:
        state.last_error_code = state.last_error_at = None


def _property(rt: Runtime, ctx: _Context, provider: AnalyticsProvider) -> bool:
    secrets = usable_secrets(rt, ctx.org_id, ctx.connection_id)
    found = _call(rt, ctx, provider, lambda: provider.read_property(secrets, ctx.ref))
    with rt.db.transaction(org_id=ctx.org_id) as session:
        prop = session.get(AnalyticsProperty, ctx.property_id)
        state = session.get(AnalyticsSyncState, ctx.property_id, with_for_update=True)
        assert prop is not None
        assert state is not None
        prop.name = found.name or prop.name
        prop.platform_status = found.platform_status
        prop.health_checked_at = rt.clock.now()
        # A property's currency and time zone can be changed in GA4. Stored days keep the
        # values they were read with; a change is recorded for the property page (5-06/5-08),
        # never applied silently to figures already stored.
        if found.platform_status != "active":
            prop.health_code = found.unavailable_reason or "property_deleted"
        elif (found.currency, found.timezone) != (prop.currency, prop.timezone):
            prop.health_code = "property_details_changed"
        else:
            prop.health_code = None
        if found.platform_status == "active":
            state.import_cursor = _cursor(*window(rt, prop, ctx.mode))
            _clear_waiting(state)
            state.updated_at = rt.clock.now()
            if ctx.first_import:
                state.import_progress = 5
    if found.platform_status != "active":
        _fail(rt, ctx, found.unavailable_reason or "property_deleted", health=True)
        return False
    return True


# ------------------------------------------------------------------ daily figures
def _cursor(first: date, last: date) -> str:
    return f"{STEP_DAYS}:{first.isoformat()}:{last.isoformat()}"


def days_cursor(step: str) -> tuple[date, date] | None:
    """``days:<first>:<last>`` → the days still to read; None for any other step."""
    parts = step.split(":")
    if len(parts) != 3 or parts[0] != STEP_DAYS:
        return None
    try:
        first, last = date.fromisoformat(parts[1]), date.fromisoformat(parts[2])
    except ValueError:
        return None
    return (first, last) if first <= last else None


def month_slice(first: date, last: date) -> date:
    """The last day of the slice starting at ``first``: the end of its calendar month."""
    next_month = _shift(first.replace(day=28), 4).replace(day=1)
    return min(last, _shift(next_month, -1))


def _days(rt: Runtime, ctx: _Context, provider: AnalyticsProvider, first: date, last: date) -> bool:
    # The first import reads calendar months; a re-read (2, 14 or 90 days) is one step.
    end = month_slice(first, last) if ctx.mode is SyncMode.INITIAL else last
    secrets = usable_secrets(rt, ctx.org_id, ctx.connection_id)
    records = _call(
        rt, ctx, provider, lambda: list(provider.read_daily(secrets, ctx.ref, first, end))
    )
    with rt.db.transaction(org_id=ctx.org_id) as session:
        prop = session.get(AnalyticsProperty, ctx.property_id)
        state = session.get(AnalyticsSyncState, ctx.property_id, with_for_update=True)
        assert prop is not None
        assert state is not None
        written = apply_daily(session, rt, prop, first, end, records)
        more = end < last
        state.import_cursor = _cursor(_shift(end, 1), last) if more else STEP_DONE
        _clear_waiting(state)
        if ctx.first_import:
            start = history_start(rt, prop)
            span = max(1, (last - start).days + 1)
            done = (end - start).days + 1
            state.import_progress = min(99, 5 + (95 * done) // span)
        state.updated_at = rt.clock.now()
    logger.info(
        "analytics_days_imported",
        extra={"property_id": str(ctx.property_id), "first": str(first), "rows": written},
    )
    return True


def dimension_key(record: AnalyticsDailyRecord) -> str:
    """What makes a row unique within its view and day."""
    if record.breakdown is AnalyticsBreakdown.TOTAL:
        return TOTAL_KEY
    if record.breakdown is AnalyticsBreakdown.CHANNEL:
        return record.channel_group or NOT_SET
    parts = (record.source, record.medium, record.campaign)
    return "|".join((p or NOT_SET).replace("\\", "\\\\").replace("|", "\\|") for p in parts)


def apply_daily(
    session: Session,
    rt: Runtime,
    prop: AnalyticsProperty,
    first: date,
    last: date,
    records: list[AnalyticsDailyRecord],
) -> int:
    """Replace the stored figures of ``first`` … ``last`` in every view. Duplicates of one
    value and day are never added together: the first is kept and the rest are counted as
    skipped. The source view keeps ``ANALYTICS_SOURCE_ROWS_PER_DAY`` values a day."""
    now = rt.clock.now()
    session.execute(
        delete(AnalyticsDaily).where(
            AnalyticsDaily.property_id == prop.id, AnalyticsDaily.day.between(first, last)
        )
    )
    kept: dict[tuple[AnalyticsBreakdown, date], dict[str, AnalyticsDailyRecord]] = defaultdict(dict)
    skipped = 0
    for r in records:
        if not first <= r.day <= last:
            skipped += 1
            continue
        bucket = kept[(r.breakdown, r.day)]
        key = dimension_key(r)
        if key in bucket:
            skipped += 1
            continue
        bucket[key] = r
    total_quality = AnalyticsQuality()
    written = 0
    for (view, _day), bucket in kept.items():
        rows = bucket
        if view is AnalyticsBreakdown.SOURCE:
            rows = _cap(bucket, rt.settings.ANALYTICS_SOURCE_ROWS_PER_DAY)
        elif view is AnalyticsBreakdown.TOTAL:
            total_quality = next(iter(bucket.values())).quality
        for key, r in rows.items():
            session.add(_row(prop, r, key, now))
            written += 1
    day = first
    while day <= last:  # the platform sends no total row for a day without activity
        if TOTAL_KEY not in kept.get((AnalyticsBreakdown.TOTAL, day), {}):
            session.add(_row(prop, _zero_day(day, total_quality), TOTAL_KEY, now))
            written += 1
        day = _shift(day, 1)
    session.flush()
    if skipped:
        logger.warning(
            "analytics_rows_skipped", extra={"property_id": str(prop.id), "count": skipped}
        )
    return written


def _cap(bucket: dict[str, AnalyticsDailyRecord], limit: int) -> dict[str, AnalyticsDailyRecord]:
    """Keep the ``limit - 1`` values with the most sessions and add the rest (with any
    "(other)" row the platform sent) into one marked "(other)" row. Sessions, engaged
    sessions, key events, purchases and revenue add up; users and new users do not (the same
    person can arrive from several sources), so they are left unknown."""
    if len(bucket) <= limit:
        return bucket
    other_key = dimension_key(
        AnalyticsDailyRecord(
            breakdown=AnalyticsBreakdown.SOURCE,
            day=date.min,
            source=OTHER,
            medium=OTHER,
            campaign=OTHER,
        )
    )
    ranked = sorted(
        ((k, r) for k, r in bucket.items() if k != other_key),
        key=lambda kr: (-(kr[1].sessions or 0), kr[0]),
    )
    keep, rest = ranked[: limit - 1], [r for _, r in ranked[limit - 1 :]]
    if other_key in bucket:
        rest.append(bucket[other_key])
    sample = rest[0]
    quality = AnalyticsQuality(
        other_row=True,
        thresholded=any(r.quality.thresholded for r in rest),
        sampled=any(r.quality.sampled for r in rest),
        truncated=any(r.quality.truncated for r in rest),
    )
    combined = AnalyticsDailyRecord(
        breakdown=AnalyticsBreakdown.SOURCE,
        day=sample.day,
        source=OTHER,
        medium=OTHER,
        campaign=OTHER,
        sessions=_sum([r.sessions for r in rest]),
        engaged_sessions=_sum([r.engaged_sessions for r in rest]),
        total_users=None,
        new_users=None,
        key_events=_sum([r.key_events for r in rest]),
        purchases=_sum([r.purchases for r in rest]),
        purchase_revenue=_sum([r.purchase_revenue for r in rest]),
        quality=quality,
    )
    logger.info(
        "analytics_source_values_combined", extra={"day": str(sample.day), "count": len(rest)}
    )
    return {**dict(keep), other_key: combined}


def _sum[N: (int, Decimal)](values: list[N | None]) -> N | None:
    """The total of values that are all known; unknown when any part is unknown (A10)."""
    if any(v is None for v in values):
        return None
    known = [v for v in values if v is not None]
    return sum(known[1:], known[0]) if known else None


def _zero_day(day: date, quality: AnalyticsQuality) -> AnalyticsDailyRecord:
    zero = Decimal(0)
    return AnalyticsDailyRecord(
        breakdown=AnalyticsBreakdown.TOTAL,
        day=day,
        sessions=0,
        engaged_sessions=0,
        total_users=0,
        new_users=0,
        key_events=zero,
        purchases=0,
        purchase_revenue=zero,
        quality=quality,
    )


def _text(value: str | None) -> str | None:
    return value[:255] if value else None


def _row(
    prop: AnalyticsProperty, r: AnalyticsDailyRecord, key: str, now: datetime
) -> AnalyticsDaily:
    return AnalyticsDaily(
        organization_id=prop.organization_id,
        property_id=prop.id,
        day=r.day,
        breakdown=r.breakdown.value,
        dimension_key=key[:1024],
        channel_group=_text(r.channel_group),
        traffic_source=_text(r.source),
        traffic_medium=_text(r.medium),
        campaign=_text(r.campaign),
        sessions=r.sessions,
        engaged_sessions=r.engaged_sessions,
        total_users=r.total_users,
        new_users=r.new_users,
        key_events=r.key_events,
        purchases=r.purchases,
        purchase_revenue=r.purchase_revenue,
        currency=prop.currency,
        other_row=r.quality.other_row,
        thresholded=r.quality.thresholded,
        sampled=r.quality.sampled,
        truncated=r.quality.truncated,
        fetched_at=now,
    )


# ------------------------------------------------------------------ end of a chain
def _finish(rt: Runtime, ctx: _Context) -> None:
    now = rt.clock.now()
    with rt.db.transaction(org_id=ctx.org_id) as session:
        prop = session.get(AnalyticsProperty, ctx.property_id)
        state = session.get(AnalyticsSyncState, ctx.property_id, with_for_update=True)
        assert prop is not None
        assert state is not None
        if prop.first_import_completed_at is None:
            prop.first_import_completed_at = now
            record_audit(
                session,
                organization_id=ctx.org_id,
                actor=WORKER,
                action="analytics_property.import_completed",
                resource_type="analytics_property",
                resource_id=ctx.property_id,
            )
        prop.status = "active"
        state.import_progress = 100
        if ctx.mode is SyncMode.INITIAL:
            state.last_quick_at = state.last_nightly_at = state.last_weekly_at = now
        elif ctx.mode is SyncMode.QUICK:
            state.last_quick_at = now
        elif ctx.mode is SyncMode.NIGHTLY:
            state.last_nightly_at = now
        else:
            state.last_weekly_at = state.last_nightly_at = now
        state.import_job_id, state.import_cursor, state.sync_mode = None, None, None
        state.last_error_code = state.last_error_at = None
        state.updated_at = now


def _fail(rt: Runtime, ctx: _Context, code: str, *, health: bool) -> None:
    with rt.db.transaction(org_id=ctx.org_id) as session:
        prop = session.get(AnalyticsProperty, ctx.property_id)
        state = session.get(AnalyticsSyncState, ctx.property_id, with_for_update=True)
        if prop is None or state is None:
            return
        now = rt.clock.now()
        state.import_job_id, state.import_cursor, state.sync_mode = None, None, None
        state.last_error_code, state.last_error_at = code[:64], now
        if health:
            prop.health_code, prop.health_checked_at = code[:64], now
        if ctx.first_import:
            prop.status = "error"
        record_audit(
            session,
            organization_id=ctx.org_id,
            actor=WORKER,
            action="analytics_property.import_failed",
            resource_type="analytics_property",
            resource_id=ctx.property_id,
            metadata={"error": code[:64]},
        )
