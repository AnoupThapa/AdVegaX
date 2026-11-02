"""Inputs and calculation for the unified metrics (Phase 6, task 6-04; registry: ``registry.py``).

``load_inputs`` reads the stored daily figures of every source in scope — stores
(``financial_daily``, finance-v1), ad accounts (account-level ``ad_performance_daily``) and
Google Analytics properties (the ``total`` view of ``analytics_daily``) — and converts each
source-day to the reporting currency with that day's rate. ``compute`` applies the registry's
formulas to a period (or one day). Everything is computed on read (Q-6-13): late refunds,
platform corrections and cost edits show at once.

Scope (Q-6-1): the whole organization, or one store. For one store, ad accounts and properties
assigned to it count — and, when the organization has only that one store, every ad account and
property counts for it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.advertising.models import AdAccount, AdPerformanceDaily, AdSyncState
from app.domains.analytics.models import (
    TOTAL_KEY,
    AnalyticsDaily,
    AnalyticsProperty,
    AnalyticsSyncState,
)
from app.domains.commerce.models import CommerceSyncState, Store
from app.domains.finance.definitions import DEFINITION_VERSION as FINANCE_VERSION
from app.domains.finance.models import FinancialDaily
from app.domains.fx.service import FxTable
from app.domains.metrics.registry import NOT_PROVIDED

AVAILABLE, UNAVAILABLE, NOT_SYNCED = "available", "unavailable", "not_synchronized"
RATIO_PLACES = Decimal("0.000001")
ZERO = Decimal(0)
# Which missing state wins when inputs are combined: a day not read says so first.
_PRECEDENCE = {NOT_SYNCED: 0, UNAVAILABLE: 1, "unsupported": 2, AVAILABLE: 3}


@dataclass(frozen=True)
class Figure:
    value: Decimal | None
    availability: str = AVAILABLE
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.availability == AVAILABLE and self.value is not None


def missing(availability: str, reason: str) -> Figure:
    return Figure(None, availability, reason)


def _worst(*figures: Figure) -> Figure | None:
    bad = [f for f in figures if not f.ok]
    if not bad:
        return None
    return min(bad, key=lambda f: _PRECEDENCE.get(f.availability, 9))


def plus(*figures: Figure) -> Figure:
    worst = _worst(*figures)
    if worst is not None:
        return Figure(None, worst.availability, worst.reason)
    return Figure(sum((f.value for f in figures if f.value is not None), ZERO))


def minus(a: Figure, b: Figure) -> Figure:
    worst = _worst(a, b)
    if worst is not None:
        return Figure(None, worst.availability, worst.reason)
    assert a.value is not None
    assert b.value is not None
    return Figure(a.value - b.value)


def ratio(numerator: Figure, denominator: Figure, zero_reason: str) -> Figure:
    worst = _worst(numerator, denominator)
    if worst is not None:
        return Figure(None, worst.availability, worst.reason)
    assert numerator.value is not None
    assert denominator.value is not None
    if denominator.value == 0:
        return missing(UNAVAILABLE, zero_reason)
    with localcontext() as ctx:
        ctx.prec = 34
        value = numerator.value / denominator.value
    return Figure(value.quantize(RATIO_PLACES, rounding=ROUND_HALF_EVEN))


# ------------------------------------------------------------------ scope and sources
@dataclass(frozen=True)
class Source:
    """One store, ad account or property in scope, as the answers list it."""

    kind: str  # store | ad_account | analytics_property
    id: uuid.UUID
    provider: str
    name: str | None
    currency: str
    timezone: str
    synced_from: date | None  # first fully read day (source time zone); None = not yet
    today: date  # the source's own today
    updated_at: datetime | None = None  # when its figures were last brought up to date


@dataclass(frozen=True)
class Scope:
    currency: str
    timezone: str
    stores: tuple[Source, ...]
    ad_accounts: tuple[Source, ...]
    properties: tuple[Source, ...]
    every_store_measured: bool  # every store in scope has a Google Analytics property

    @property
    def sources(self) -> tuple[Source, ...]:
        return (*self.stores, *self.ad_accounts, *self.properties)


def _today(now: datetime, timezone: str) -> date:
    return now.astimezone(ZoneInfo(timezone)).date()


def _store_synced_from(store: Store, tz: tzinfo) -> date | None:
    """As on the store page: the day after the history start, once the first import is done."""
    if store.first_import_completed_at is None or store.history_from is None:
        return None
    return date.fromordinal(store.history_from.astimezone(tz).date().toordinal() + 1)


def load_scope(
    session: Session,
    *,
    organization_id: uuid.UUID,
    currency: str,
    timezone: str,
    now: datetime,
    store_id: uuid.UUID | None = None,
) -> Scope:
    stores = list(
        session.execute(
            select(Store).where(Store.organization_id == organization_id).order_by(Store.created_at)
        ).scalars()
    )
    accounts = list(
        session.execute(
            select(AdAccount)
            .where(AdAccount.organization_id == organization_id)
            .order_by(AdAccount.created_at)
        ).scalars()
    )
    props = list(
        session.execute(
            select(AnalyticsProperty)
            .where(AnalyticsProperty.organization_id == organization_id)
            .order_by(AnalyticsProperty.created_at)
        ).scalars()
    )
    store_updates = dict(
        session.execute(
            select(CommerceSyncState.store_id, CommerceSyncState.last_reconciled_at).where(
                CommerceSyncState.organization_id == organization_id
            )
        ).all()
    )
    account_updates = dict(
        session.execute(
            select(AdSyncState.ad_account_id, AdSyncState.last_quick_at).where(
                AdSyncState.organization_id == organization_id
            )
        ).all()
    )
    property_updates = dict(
        session.execute(
            select(AnalyticsSyncState.property_id, AnalyticsSyncState.last_quick_at).where(
                AnalyticsSyncState.organization_id == organization_id
            )
        ).all()
    )
    if store_id is not None:
        single = len(stores) == 1 and stores[0].id == store_id
        stores = [s for s in stores if s.id == store_id]
        if not single:  # several stores: only what is assigned to this one
            accounts = [a for a in accounts if a.store_id == store_id]
            props = [p for p in props if p.store_id == store_id]
    measured = {p.store_id for p in props}
    every_store = bool(stores) and (
        (len(stores) == 1 and bool(props)) or all(s.id in measured for s in stores)
    )
    return Scope(
        currency=currency,
        timezone=timezone,
        stores=tuple(
            Source(
                "store",
                s.id,
                s.provider,
                s.name or s.domain,
                s.currency,
                s.timezone,
                _store_synced_from(s, ZoneInfo(s.timezone)),
                _today(now, s.timezone),
                store_updates.get(s.id) or s.first_import_completed_at,
            )
            for s in stores
        ),
        ad_accounts=tuple(
            Source(
                "ad_account",
                a.id,
                a.provider,
                a.name,
                a.currency,
                a.timezone,
                a.history_from if a.first_import_completed_at else None,
                _today(now, a.timezone),
                account_updates.get(a.id) or a.first_import_completed_at,
            )
            for a in accounts
        ),
        properties=tuple(
            Source(
                "analytics_property",
                p.id,
                p.provider,
                p.name,
                p.currency,
                p.timezone,
                p.history_from if p.first_import_completed_at else None,
                _today(now, p.timezone),
                property_updates.get(p.id) or p.first_import_completed_at,
            )
            for p in props
        ),
        every_store_measured=every_store,
    )


# ------------------------------------------------------------------ daily inputs
@dataclass
class DayInputs:
    """One report day's inputs, already in the reporting currency."""

    net_sales: list[Figure] = field(default_factory=list)
    orders: list[Figure] = field(default_factory=list)
    product_cost: list[Figure] = field(default_factory=list)
    ad_spend: list[Figure] = field(default_factory=list)
    sessions: list[Figure] = field(default_factory=list)
    analytics_purchases: list[Figure] = field(default_factory=list)
    analytics_revenue: list[Figure] = field(default_factory=list)


@dataclass
class Inputs:
    scope: Scope
    first: date
    last: date
    days: dict[date, DayInputs]

    def period(self, first: date | None = None, last: date | None = None) -> DayInputs:
        """Every input of the days between ``first`` and ``last`` (default: the whole range)."""
        merged = DayInputs()
        for day, inputs in self.days.items():
            if (first is None or day >= first) and (last is None or day <= last):
                for name in DayInputs.__dataclass_fields__:
                    getattr(merged, name).extend(getattr(inputs, name))
        return merged


def synced(source: Source, day: date) -> bool:
    return source.synced_from is not None and source.synced_from <= day <= source.today


def load_inputs(
    session: Session,
    scope: Scope,
    first: date,
    last: date,
    fx: FxTable,
) -> Inputs:
    days = {
        date.fromordinal(o): DayInputs() for o in range(first.toordinal(), last.toordinal() + 1)
    }
    target = scope.currency

    def money(value: Decimal | None, currency: str, day: date) -> Figure:
        if value is None:
            return missing(UNAVAILABLE, "missing_product_costs")
        converted = fx.convert(value, currency, target, day)
        if converted is None:
            return missing(UNAVAILABLE, "no_exchange_rate")
        return Figure(converted)

    # Stores: finance-v1 daily components (a read day without a row had no activity).
    store_ids = [s.id for s in scope.stores]
    finance = (
        {
            (r.store_id, r.day): r
            for r in session.execute(
                select(FinancialDaily).where(
                    FinancialDaily.store_id.in_(store_ids),
                    FinancialDaily.definition_version == FINANCE_VERSION,
                    FinancialDaily.day.between(first, last),
                ),
            ).scalars()
        }
        if store_ids
        else {}
    )
    for store in scope.stores:
        for day, inputs in days.items():
            if not synced(store, day):
                gap = missing(NOT_SYNCED, NOT_SYNCED)
                inputs.net_sales.append(gap)
                inputs.orders.append(gap)
                inputs.product_cost.append(gap)
                continue
            row = finance.get((store.id, day))
            if row is not None and row.other_currency_orders:
                foreign = missing(UNAVAILABLE, "other_currency_orders")  # Q-2B-5
                inputs.net_sales.append(foreign)
                inputs.orders.append(foreign)
                inputs.product_cost.append(foreign)
                continue
            inputs.net_sales.append(money(row.net_sales if row else ZERO, store.currency, day))
            inputs.orders.append(Figure(Decimal(row.orders_count if row else 0)))
            inputs.product_cost.append(money(row.cogs if row else ZERO, store.currency, day))

    # Ad accounts: the account-level rows (a read day always has one, zeros included).
    account_ids = [a.id for a in scope.ad_accounts]
    spend = (
        {
            (perf.ad_account_id, perf.day): perf
            for perf in session.execute(
                select(AdPerformanceDaily).where(
                    AdPerformanceDaily.ad_account_id.in_(account_ids),
                    AdPerformanceDaily.level == "account",
                    AdPerformanceDaily.day.between(first, last),
                ),
            ).scalars()
        }
        if account_ids
        else {}
    )
    for account in scope.ad_accounts:
        for day, inputs in days.items():
            perf = spend.get((account.id, day))
            if not synced(account, day) or perf is None:
                inputs.ad_spend.append(missing(NOT_SYNCED, NOT_SYNCED))
                continue
            cost = perf.cost
            if cost is None:
                inputs.ad_spend.append(missing(UNAVAILABLE, "not_provided"))
                continue
            converted = fx.convert(cost, account.currency, target, day)
            inputs.ad_spend.append(
                Figure(converted)
                if converted is not None
                else missing(UNAVAILABLE, "no_exchange_rate")
            )

    # Google Analytics: the total view (a read day always has a row, zeros included).
    property_ids = [p.id for p in scope.properties]
    visits = (
        {
            (visit.property_id, visit.day): visit
            for visit in session.execute(
                select(AnalyticsDaily).where(
                    AnalyticsDaily.property_id.in_(property_ids),
                    AnalyticsDaily.breakdown == "total",
                    AnalyticsDaily.dimension_key == TOTAL_KEY,
                    AnalyticsDaily.day.between(first, last),
                ),
            ).scalars()
        }
        if property_ids
        else {}
    )
    for prop in scope.properties:
        for day, inputs in days.items():
            visit = visits.get((prop.id, day))
            if not synced(prop, day) or visit is None:
                gap = missing(NOT_SYNCED, NOT_SYNCED)
                inputs.sessions.append(gap)
                inputs.analytics_purchases.append(gap)
                inputs.analytics_revenue.append(gap)
                continue
            inputs.sessions.append(_count(visit.sessions))
            inputs.analytics_purchases.append(_count(visit.purchases))
            if visit.purchase_revenue is None:
                inputs.analytics_revenue.append(missing(UNAVAILABLE, "not_provided"))
            else:
                converted = fx.convert(visit.purchase_revenue, prop.currency, target, day)
                inputs.analytics_revenue.append(
                    Figure(converted)
                    if converted is not None
                    else missing(UNAVAILABLE, "no_exchange_rate")
                )
    return Inputs(scope, first, last, days)


def _count(value: int | None) -> Figure:
    return Figure(Decimal(value)) if value is not None else missing(UNAVAILABLE, "not_provided")


# ------------------------------------------------------------------ the formulas
def _total(figures: list[Figure], present: bool, absent_reason: str) -> Figure:
    if not present:
        return missing(UNAVAILABLE, absent_reason)  # nothing of that kind is connected
    return plus(*figures)


def compute(scope: Scope, inputs: DayInputs) -> dict[str, Figure]:
    """Every registry metric for one day or a period of ``inputs``."""
    has_store, has_ads, has_ga = bool(scope.stores), bool(scope.ad_accounts), bool(scope.properties)
    net_sales = _total(inputs.net_sales, has_store, "no_store")
    orders = _total(inputs.orders, has_store, "no_store")
    product_cost = _total(inputs.product_cost, has_store, "no_store")
    ad_spend = _total(inputs.ad_spend, has_ads, "no_ad_account")
    gross_profit = minus(net_sales, product_cost)
    sessions = _total(inputs.sessions, has_ga, "no_analytics_property")
    figures = {
        "net_sales": net_sales,
        "orders": orders,
        "product_cost": product_cost,
        "gross_profit": gross_profit,
        "gross_margin": ratio(gross_profit, net_sales, "no_net_sales"),
        "ad_spend": ad_spend,
        "profit_after_ad_spend": minus(gross_profit, ad_spend),
        "blended_roas": ratio(net_sales, ad_spend, "no_ad_spend"),
        "cost_per_order": ratio(ad_spend, orders, "no_orders"),
        "ad_spend_share": ratio(ad_spend, net_sales, "no_net_sales"),
        "sessions": sessions,
        "analytics_purchases": _total(inputs.analytics_purchases, has_ga, "no_analytics_property"),
        "analytics_revenue": _total(inputs.analytics_revenue, has_ga, "no_analytics_property"),
        "store_conversion_rate": (
            ratio(orders, sessions, "no_sessions")
            if scope.every_store_measured
            else missing(UNAVAILABLE, "not_every_store_measured")
        ),
    }
    for key, (availability, reason) in NOT_PROVIDED.items():
        figures[key] = missing(availability, reason)
    return figures
