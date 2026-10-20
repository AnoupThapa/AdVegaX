"""Reading analytics properties and their figures (task 5-07, PLAN §10-§11).

Same rules as the store and advertising APIs: every member can read, managers and above can
"Sync now", another organization's data is a 404, money is an exact decimal string and every
missing value carries an availability and a reason instead of a 0 (A10).

Figures are **platform-reported** ("Reported by Google Analytics") and never added to store or
ad figures. A period's totals come from the total view; a channel's or a source's from its own
rows. Sessions, engaged sessions, new users, key events, purchases and revenue add up over days;
**users never do** (Q-5-5): they are given for one day only. Rates are derived on read (A5) and
are "unavailable" with a reason when their divisor is 0. A day that was not read is "not
synchronized"; a period containing one has no totals. The last days
(``ANALYTICS_PROCESSING_DAYS``) are marked as still being processed by Google (Q-5-6), and the
platform's data-quality notes travel with every day and period (Q-5-8).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.domains.analytics.importer import (
    WAITING,
    chain_running,
    local_today,
    request_sync,
)
from app.domains.analytics.models import (
    BREAKDOWNS,
    TOTAL_KEY,
    AnalyticsDaily,
    AnalyticsProperty,
    AnalyticsSyncState,
)
from app.domains.analytics.schemas import (
    AnalyticsDailyMetricsOut,
    AnalyticsDayOut,
    AnalyticsFiguresOut,
    AnalyticsHealthOut,
    AnalyticsItemOut,
    AnalyticsPropertyOut,
    AnalyticsQualityOut,
    AnalyticsResyncOut,
    AnalyticsSyncOut,
)
from app.domains.commerce.schemas import FigureOut
from app.domains.finance.definitions import minor_units
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.tenancy import TenantContext
from app.runtime import Runtime

SOURCE = "platform_reported"
NOT_SYNCHRONIZED = "not_synchronized"
USERS_PER_DAY_ONLY = "users_per_day_only"
RATE_PLACES = Decimal("0.000001")  # rates and per-session money: six decimals, half-even
DEFAULT_DAYS = 30
MAX_ITEMS = 500


@dataclass(frozen=True)
class _PropertyRow:
    prop: AnalyticsProperty
    state: AnalyticsSyncState | None
    connection: ExternalConnection
    linked: bool


@dataclass
class Sums:
    """Measures of a day or a period; None = the platform did not provide one of them.
    ``users`` is set for a single day only (Q-5-5)."""

    sessions: int | None = 0
    engaged_sessions: int | None = 0
    new_users: int | None = 0
    key_events: Decimal | None = Decimal(0)
    purchases: int | None = 0
    purchase_revenue: Decimal | None = Decimal(0)
    users: int | None = None
    days: int = 0
    other_row: bool = False
    thresholded: bool = False
    sampled: bool = False
    truncated: bool = False

    def add(self, row: AnalyticsDaily) -> None:
        def plus(total: Any, value: Any) -> Any:
            return None if total is None or value is None else total + value

        self.sessions = plus(self.sessions, row.sessions)
        self.engaged_sessions = plus(self.engaged_sessions, row.engaged_sessions)
        self.new_users = plus(self.new_users, row.new_users)
        self.key_events = plus(self.key_events, row.key_events)
        self.purchases = plus(self.purchases, row.purchases)
        self.purchase_revenue = plus(self.purchase_revenue, row.purchase_revenue)
        self.days += 1
        self.users = row.total_users if self.days == 1 else None  # never added across days
        self.other_row |= row.other_row
        self.thresholded |= row.thresholded
        self.sampled |= row.sampled
        self.truncated |= row.truncated


@dataclass(frozen=True)
class _Period:
    first: date
    last: date
    today: date
    synced_from: date | None

    @property
    def single_day(self) -> bool:
        return self.first == self.last

    @property
    def synced(self) -> bool:
        """Every day of the period has been read."""
        return (
            self.synced_from is not None
            and self.first >= self.synced_from
            and self.last <= self.today
        )

    def day_synced(self, day: date) -> bool:
        return self.synced_from is not None and self.synced_from <= day <= self.today


# ---------------------------------------------------------------------- figures
def _rate(numerator: Any, denominator: Any, zero_reason: str) -> FigureOut:
    if numerator is None or denominator is None:
        return FigureOut(value=None, availability="unavailable", reason="not_provided")
    if Decimal(denominator) == 0:
        return FigureOut(value=None, availability="unavailable", reason=zero_reason)
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        RATE_PLACES, rounding=ROUND_HALF_EVEN
    )
    return FigureOut(value=value, availability="available")


def _users(sums: Sums, single_day: bool) -> FigureOut:
    if not single_day:
        return FigureOut(value=None, availability="unavailable", reason=USERS_PER_DAY_ONLY)
    if sums.users is None:
        return FigureOut(value=None, availability="unavailable", reason="not_provided")
    return FigureOut(value=Decimal(sums.users), availability="available")


def _quality(sums: Sums) -> AnalyticsQualityOut:
    return AnalyticsQualityOut(
        other_row=sums.other_row,
        thresholded=sums.thresholded,
        sampled=sums.sampled,
        truncated=sums.truncated,
    )


def _measures(sums: Sums, *, single_day: bool) -> dict[str, Any]:
    return {
        "sessions": sums.sessions,
        "engaged_sessions": sums.engaged_sessions,
        "total_users": _users(sums, single_day),
        "new_users": sums.new_users,
        "key_events": sums.key_events,
        "purchases": sums.purchases,
        "purchase_revenue": sums.purchase_revenue,
        "engagement_rate": _rate(sums.engaged_sessions, sums.sessions, "no_sessions"),
        "key_events_per_session": _rate(sums.key_events, sums.sessions, "no_sessions"),
        "purchase_conversion_rate": _rate(sums.purchases, sums.sessions, "no_sessions"),
        "revenue_per_session": _rate(sums.purchase_revenue, sums.sessions, "no_sessions"),
        "quality": _quality(sums),
    }


def figures(sums: Sums, *, single_day: bool) -> AnalyticsFiguresOut:
    return AnalyticsFiguresOut(availability="available", **_measures(sums, single_day=single_day))


def _not_synced() -> dict[str, Any]:
    missing = FigureOut(value=None, availability=NOT_SYNCHRONIZED, reason=NOT_SYNCHRONIZED)
    return {
        "availability": NOT_SYNCHRONIZED,
        "reason": NOT_SYNCHRONIZED,
        "sessions": None,
        "engaged_sessions": None,
        "total_users": missing,
        "new_users": None,
        "key_events": None,
        "purchases": None,
        "purchase_revenue": None,
        "engagement_rate": missing,
        "key_events_per_session": missing,
        "purchase_conversion_rate": missing,
        "revenue_per_session": missing,
        "quality": AnalyticsQualityOut(
            other_row=False, thresholded=False, sampled=False, truncated=False
        ),
    }


def not_synced_figures() -> AnalyticsFiguresOut:
    return AnalyticsFiguresOut(**_not_synced())


# ---------------------------------------------------------------------- the service
class AnalyticsReadService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # ------------------------------------------------------------------ properties
    def _rows(
        self, session: Session, ctx: TenantContext, property_id: uuid.UUID | None
    ) -> list[_PropertyRow]:
        active_link = (
            select(OrganizationResourceLink.id)
            .where(
                OrganizationResourceLink.external_resource_id
                == AnalyticsProperty.external_resource_id,
                OrganizationResourceLink.status == "active",
            )
            .exists()
        )
        stmt = (
            select(AnalyticsProperty, AnalyticsSyncState, ExternalConnection, active_link)
            .outerjoin(AnalyticsSyncState, AnalyticsSyncState.property_id == AnalyticsProperty.id)
            .join(ExternalResource, ExternalResource.id == AnalyticsProperty.external_resource_id)
            .join(ExternalConnection, ExternalConnection.id == ExternalResource.connection_id)
            .where(AnalyticsProperty.organization_id == ctx.organization_id)
            .order_by(AnalyticsProperty.created_at, AnalyticsProperty.id)
        )
        if property_id is not None:
            stmt = stmt.where(AnalyticsProperty.id == property_id)
        return [_PropertyRow(p, st, c, bool(linked)) for p, st, c, linked in session.execute(stmt)]

    def _one(self, session: Session, ctx: TenantContext, property_id: uuid.UUID) -> _PropertyRow:
        rows = self._rows(session, ctx, property_id)
        if not rows:
            raise NotFound()
        return rows[0]

    def _property_out(self, row: _PropertyRow) -> AnalyticsPropertyOut:
        prop, state = row.prop, row.state
        running = state is not None and chain_running(self.rt, state)
        waiting = state is not None and state.last_error_code == WAITING
        return AnalyticsPropertyOut(
            id=prop.id,
            resource_id=prop.external_resource_id,
            provider=prop.provider,
            source=SOURCE,
            external_property_id=prop.external_property_id,
            name=prop.name,
            account_name=prop.account_name,
            currency=prop.currency,
            currency_minor_units=minor_units(prop.currency),
            timezone=prop.timezone,
            status=prop.status,
            platform_status=prop.platform_status,
            linked=row.linked,
            connection_status=row.connection.status,
            history_from=prop.history_from,
            first_import_completed_at=prop.first_import_completed_at,
            sync=AnalyticsSyncOut(
                running=running,
                mode=state.sync_mode if state is not None and running else None,
                progress=(
                    state.import_progress
                    if state is not None and prop.first_import_completed_at is None
                    else None
                ),
                waiting_for_allowance=running and waiting,
                last_quick_at=state.last_quick_at if state else None,
                last_nightly_at=state.last_nightly_at if state else None,
                last_weekly_at=state.last_weekly_at if state else None,
                last_error_code=state.last_error_code if state and not waiting else None,
                last_error_at=state.last_error_at if state and not waiting else None,
            ),
            health=(
                AnalyticsHealthOut(code=prop.health_code, checked_at=prop.health_checked_at)
                if prop.health_checked_at is not None
                else None
            ),
            created_at=prop.created_at,
        )

    def list_properties(self, ctx: TenantContext) -> list[AnalyticsPropertyOut]:
        authorize(ctx, Permission.ANALYTICS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return [self._property_out(row) for row in self._rows(session, ctx, None)]

    def get_property(self, ctx: TenantContext, property_id: uuid.UUID) -> AnalyticsPropertyOut:
        authorize(ctx, Permission.ANALYTICS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return self._property_out(self._one(session, ctx, property_id))

    def resync(self, ctx: TenantContext, property_id: uuid.UUID) -> AnalyticsResyncOut:
        """ "Sync now": the last 14 days (limited per property)."""
        authorize(ctx, Permission.ANALYTICS_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            prop = self._one(session, ctx, property_id).prop
            job_id, mode = request_sync(session, self.rt, prop, requested_by=ctx.user_id)
            return AnalyticsResyncOut(property_id=prop.id, job_id=job_id, mode=mode.value)

    # ------------------------------------------------------------------ figures
    def _period(
        self, prop: AnalyticsProperty, from_day: date | None, to_day: date | None
    ) -> _Period:
        today = local_today(self.rt, prop.timezone)
        last = to_day or today
        first = from_day or date.fromordinal(last.toordinal() - (DEFAULT_DAYS - 1))
        span = last.toordinal() - first.toordinal() + 1
        if span < 1 or span > self.rt.settings.METRICS_MAX_DAYS:
            raise ValidationFailed(details=[{"field": "from", "issue": "invalid_range"}])
        synced_from = prop.history_from if prop.first_import_completed_at else None
        return _Period(first, last, today, synced_from)

    def daily_metrics(
        self,
        ctx: TenantContext,
        property_id: uuid.UUID,
        *,
        from_day: date | None,
        to_day: date | None,
        breakdown: str = "total",
        limit: int = 100,
    ) -> AnalyticsDailyMetricsOut:
        """The total view day by day with period totals, or a breakdown (channel, or source /
        medium / campaign) with each value's period figures, most sessions first."""
        authorize(ctx, Permission.ANALYTICS_VIEW)
        if breakdown not in BREAKDOWNS:
            raise ValidationFailed(details=[{"field": "breakdown", "issue": "invalid"}])
        if not 1 <= limit <= MAX_ITEMS:
            raise ValidationFailed(details=[{"field": "limit", "issue": "out_of_range"}])
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            prop = self._one(session, ctx, property_id).prop
            period = self._period(prop, from_day, to_day)
            rows = list(
                session.execute(
                    select(AnalyticsDaily)
                    .where(
                        AnalyticsDaily.organization_id == ctx.organization_id,
                        AnalyticsDaily.property_id == prop.id,
                        AnalyticsDaily.breakdown.in_({"total", breakdown}),
                        AnalyticsDaily.day >= period.first,
                        AnalyticsDaily.day <= period.last,
                    )
                    .order_by(AnalyticsDaily.day, AnalyticsDaily.dimension_key)
                ).scalars()
            )
            processing_from = date.fromordinal(
                period.today.toordinal() - max(0, self.rt.settings.ANALYTICS_PROCESSING_DAYS - 1)
            )
            totals_by_day = {r.day: r for r in rows if r.breakdown == "total"}
            days, totals = self._days(period, totals_by_day, processing_from)
            items: list[AnalyticsItemOut] = []
            count = 0
            if breakdown != "total" and period.synced:
                items, count = self._items(
                    [r for r in rows if r.breakdown == breakdown], period, limit
                )
            return AnalyticsDailyMetricsOut(
                property_id=prop.id,
                source=SOURCE,
                breakdown=breakdown,
                currency=prop.currency,
                currency_minor_units=minor_units(prop.currency),
                timezone=prop.timezone,
                from_day=period.first,
                to_day=period.last,
                synced_from=period.synced_from,
                processing_from=processing_from,
                totals=totals,
                days=days if breakdown == "total" else [],
                items=items,
                item_count=count,
            )

    def _days(
        self, period: _Period, rows: dict[date, AnalyticsDaily], processing_from: date
    ) -> tuple[list[AnalyticsDayOut], AnalyticsFiguresOut]:
        days: list[AnalyticsDayOut] = []
        total, complete = Sums(), True
        for ordinal in range(period.first.toordinal(), period.last.toordinal() + 1):
            day = date.fromordinal(ordinal)
            row = rows.get(day)
            processing = day >= processing_from
            if row is None or not period.day_synced(day):
                complete = False  # never read: "not synchronized", never 0
                days.append(AnalyticsDayOut(day=day, processing=processing, **_not_synced()))
                continue
            one = Sums()
            one.add(row)
            total.add(row)
            days.append(
                AnalyticsDayOut(
                    day=day,
                    processing=processing,
                    availability="available",
                    **_measures(one, single_day=True),
                )
            )
        if not complete:
            return days, not_synced_figures()
        return days, figures(total, single_day=period.single_day)

    def _items(
        self, rows: list[AnalyticsDaily], period: _Period, limit: int
    ) -> tuple[list[AnalyticsItemOut], int]:
        by_key: dict[str, tuple[AnalyticsDaily, Sums]] = {}
        for row in rows:
            if row.dimension_key == TOTAL_KEY:
                continue
            found = by_key.get(row.dimension_key)
            if found is None:
                found = (row, Sums())
                by_key[row.dimension_key] = found
            found[1].add(row)
        ranked = sorted(by_key.items(), key=lambda kv: (-(kv[1][1].sessions or 0), kv[0]))
        items = [
            AnalyticsItemOut(
                key=key,
                channel_group=first.channel_group,
                source=first.traffic_source,
                medium=first.traffic_medium,
                campaign=first.campaign,
                # A value missing on a day had no sessions that day; its users stay per day.
                figures=figures(sums, single_day=period.single_day),
            )
            for key, (first, sums) in ranked[:limit]
        ]
        return items, len(ranked)
