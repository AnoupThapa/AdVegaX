"""Inputs and calculation of the funnel, ``funnel-v1`` (Phase 7, task 7-04; registry:
``registry.py``).

``load_funnel`` reads, for every source in scope (the Phase 6 scope: the whole organization or
one store, Q-6-1) and every day of the period:

* **ad accounts** — the account-level rows of ``ad_performance_daily``: impressions, clicks,
  and each platform's own funnel actions and conversions (Q-7-4);
* **Google Analytics properties** — the ``total`` view (sessions, ``view_item``,
  ``add_to_cart``, ``begin_checkout`` events, purchases) and the ``channel`` view (Q-7-3);
* **stores** — orders, from the Phase 6 inputs (``metrics.engine``), so the funnel's purchases
  are exactly the Overview's orders.

``whole``, ``platforms`` and ``channels`` apply the registry to a period. Nothing is stored:
the funnel is computed on read (Q-7-8). Counts are events, not people (Q-7-5).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.advertising.models import AdPerformanceDaily
from app.domains.analytics.models import TOTAL_KEY, AnalyticsDaily
from app.domains.funnel.registry import (
    CHANNEL_STAGES,
    CHANNEL_STEPS,
    PLATFORM_REPORTS,
    PLATFORM_STAGES,
    STAGES,
    STEPS,
    ZERO_REASONS,
    Step,
)
from app.domains.metrics.engine import (
    NOT_SYNCED,
    UNAVAILABLE,
    Figure,
    Inputs,
    Scope,
    missing,
    plus,
    ratio,
    synced,
)

UNSUPPORTED = "unsupported"
GAP = missing(NOT_SYNCED, NOT_SYNCED)
ZERO = Decimal(0)
GA_STAGES = ("landing_page_views", "product_views", "adds_to_cart", "checkouts")
GA_COLUMNS = {
    "landing_page_views": "sessions",
    "product_views": "item_view_events",
    "adds_to_cart": "add_to_carts",
    "checkouts": "checkouts",
    "analytics_purchases": "purchases",
}
PLATFORM_COLUMNS = {
    "impressions": "impressions",
    "clicks": "clicks",
    "landing_page_views": "landing_page_views",
    "product_views": "content_views",
    "adds_to_cart": "adds_to_cart",
    "checkouts": "checkouts_initiated",
    "purchases": "conversions",
}


def _figure(value: int | Decimal | None) -> Figure:
    """A stored count: None means not read yet (e.g. before the one-time re-read)."""
    return GAP if value is None else Figure(Decimal(value))


@dataclass
class FunnelDay:
    """One report day's inputs per stage, before they are added up."""

    ads: dict[str, list[Figure]] = field(default_factory=lambda: defaultdict(list))
    # per platform (provider code) → stage → figures of its accounts
    platforms: dict[str, dict[str, list[Figure]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list))
    )
    analytics: dict[str, list[Figure]] = field(default_factory=lambda: defaultdict(list))
    # per Google Analytics channel → stage → figures; ``channel_gaps``: days not read
    channels: dict[str, dict[str, list[Figure]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list))
    )
    channel_gaps: list[Figure] = field(default_factory=list)
    orders: list[Figure] = field(default_factory=list)


@dataclass
class FunnelInputs:
    scope: Scope
    first: date
    last: date
    days: dict[date, FunnelDay]

    def period(self, first: date | None = None, last: date | None = None) -> FunnelDay:
        merged = FunnelDay()
        for day, d in self.days.items():
            if (first is not None and day < first) or (last is not None and day > last):
                continue
            for stage, figures in d.ads.items():
                merged.ads[stage].extend(figures)
            for provider, stages in d.platforms.items():
                for stage, figures in stages.items():
                    merged.platforms[provider][stage].extend(figures)
            for stage, figures in d.analytics.items():
                merged.analytics[stage].extend(figures)
            for channel, stages in d.channels.items():
                for stage, figures in stages.items():
                    merged.channels[channel][stage].extend(figures)
            merged.channel_gaps.extend(d.channel_gaps)
            merged.orders.extend(d.orders)
        return merged


def load_funnel(session: Session, scope: Scope, metrics: Inputs) -> FunnelInputs:
    """The funnel's daily inputs for the period of ``metrics`` (the Phase 6 inputs, which give
    the store orders)."""
    first, last = metrics.first, metrics.last
    days = {d: FunnelDay(orders=list(metrics.days[d].orders)) for d in metrics.days}

    accounts = {a.id: a for a in scope.ad_accounts}
    rows: dict[tuple[uuid.UUID, date], AdPerformanceDaily] = {}
    if accounts:
        for stored in session.execute(
            select(AdPerformanceDaily).where(
                AdPerformanceDaily.ad_account_id.in_(list(accounts)),
                AdPerformanceDaily.level == "account",
                AdPerformanceDaily.day.between(first, last),
            )
        ).scalars():
            rows[(stored.ad_account_id, stored.day)] = stored
    for account in scope.ad_accounts:
        reported = PLATFORM_REPORTS.get(account.provider, ("impressions", "clicks", "purchases"))
        for day, d in days.items():
            perf = rows.get((account.id, day))
            if not synced(account, day) or perf is None:
                for stage in ("impressions", "clicks"):
                    d.ads[stage].append(GAP)
                for stage in reported:
                    d.platforms[account.provider][stage].append(GAP)
                continue
            for stage in ("impressions", "clicks"):
                d.ads[stage].append(_figure(getattr(perf, PLATFORM_COLUMNS[stage])))
            for stage in reported:
                d.platforms[account.provider][stage].append(
                    _figure(getattr(perf, PLATFORM_COLUMNS[stage]))
                )

    props = {p.id: p for p in scope.properties}
    totals: dict[tuple[uuid.UUID, date], AnalyticsDaily] = {}
    channel_rows: dict[tuple[uuid.UUID, date], list[AnalyticsDaily]] = defaultdict(list)
    if props:
        for visit in session.execute(
            select(AnalyticsDaily).where(
                AnalyticsDaily.property_id.in_(list(props)),
                AnalyticsDaily.breakdown.in_(("total", "channel")),
                AnalyticsDaily.day.between(first, last),
            )
        ).scalars():
            if visit.breakdown == "total" and visit.dimension_key == TOTAL_KEY:
                totals[(visit.property_id, visit.day)] = visit
            elif visit.breakdown == "channel":
                channel_rows[(visit.property_id, visit.day)].append(visit)
    for prop in scope.properties:
        for day, d in days.items():
            total = totals.get((prop.id, day))
            if not synced(prop, day) or total is None:
                for stage in GA_COLUMNS:
                    d.analytics[stage].append(GAP)
                d.channel_gaps.append(GAP)
                continue
            for stage, column in GA_COLUMNS.items():
                d.analytics[stage].append(_figure(getattr(total, column)))
            for row in channel_rows.get((prop.id, day), []):
                name = row.channel_group or "(not set)"
                for stage, column in GA_COLUMNS.items():
                    d.channels[name][stage].append(_figure(getattr(row, column)))
    return FunnelInputs(scope, first, last, days)


# ------------------------------------------------------------------ the formulas
@dataclass(frozen=True)
class StepFigure:
    step: Step
    rate: Figure | None  # None: different sources — no rate (Q-7-2)


def _total(figures: list[Figure], present: bool, absent_reason: str) -> Figure:
    if not present:
        return missing(UNAVAILABLE, absent_reason)
    return plus(*figures)


def _steps(
    steps: tuple[Step, ...], stages: dict[str, Figure], *, store_ok: bool
) -> list[StepFigure]:
    found = []
    for step in steps:
        if step.kind == "different_sources":
            found.append(StepFigure(step, None))
            continue
        if step.kind == "store_conversion" and not store_ok:
            found.append(StepFigure(step, missing(UNAVAILABLE, "not_every_store_measured")))
            continue
        earlier, later = stages[step.from_stage], stages[step.to_stage]
        found.append(StepFigure(step, ratio(later, earlier, ZERO_REASONS[step.from_stage])))
    return found


def whole(scope: Scope, day: FunnelDay) -> tuple[dict[str, Figure], list[StepFigure]]:
    """The whole business's funnel for one day or a period (Q-7-1, Q-7-2)."""
    has_ads, has_ga, has_store = bool(scope.ad_accounts), bool(scope.properties), bool(scope.stores)
    stages: dict[str, Figure] = {
        "impressions": _total(day.ads["impressions"], has_ads, "no_ad_account"),
        "clicks": _total(day.ads["clicks"], has_ads, "no_ad_account"),
    }
    for stage in (*GA_STAGES, "analytics_purchases"):
        stages[stage] = _total(day.analytics[stage], has_ga, "no_analytics_property")
    stages["purchases"] = _total(day.orders, has_store, "no_store")
    # A property that reports visits but none of these events does not send them (its
    # Google Analytics set-up): say so instead of showing 0 (plan §2A, item 3).
    sessions = stages["landing_page_views"]
    if sessions.ok and sessions.value:
        for stage in ("product_views", "adds_to_cart", "checkouts"):
            if stages[stage].ok and stages[stage].value == ZERO:
                stages[stage] = missing(UNAVAILABLE, "no_events_reported")
    ordered = {s.key: stages[s.key] for s in STAGES}
    return ordered, _steps(STEPS, ordered, store_ok=scope.every_store_measured)


def platform_steps(provider: str) -> tuple[Step, ...]:
    reported = PLATFORM_REPORTS.get(provider, ("impressions", "clicks", "purchases"))
    return tuple(Step(a, b, "same_source") for a, b in pairwise(reported))


def platforms(
    scope: Scope, day: FunnelDay
) -> list[tuple[str, int, dict[str, Figure], list[StepFigure]]]:
    """Each platform's own funnel, as it reports it; never added across platforms."""
    found = []
    for provider in sorted({a.provider for a in scope.ad_accounts}):
        reported = PLATFORM_REPORTS.get(provider, ("impressions", "clicks", "purchases"))
        stages = {
            s.key: (
                plus(*day.platforms[provider][s.key])
                if s.key in reported
                else missing(UNSUPPORTED, "not_provided_by_platform")
            )
            for s in PLATFORM_STAGES
        }
        accounts = sum(1 for a in scope.ad_accounts if a.provider == provider)
        found.append(
            (provider, accounts, stages, _steps(platform_steps(provider), stages, store_ok=True))
        )
    return found


def channels(
    scope: Scope, day: FunnelDay
) -> tuple[list[tuple[str, dict[str, Figure], list[StepFigure]]], Figure | None]:
    """Each Google Analytics channel's funnel, most sessions first; or why there are none."""
    if not scope.properties:
        return [], missing(UNAVAILABLE, "no_analytics_property")
    if day.channel_gaps:
        return [], GAP
    found = []
    for name, by_stage in day.channels.items():
        stages = {s.key: plus(*by_stage[s.key]) for s in CHANNEL_STAGES}
        found.append((name, stages, _steps(CHANNEL_STEPS, stages, store_ok=True)))
    found.sort(key=lambda c: (-(c[1]["landing_page_views"].value or 0), c[0]))
    return found, None
