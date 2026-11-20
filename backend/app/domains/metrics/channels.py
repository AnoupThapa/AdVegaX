"""Figures by channel (Phase 6, task 6-05, PLAN §8, Q-6-6).

* **Per ad platform** (Google Ads, Meta): what the platform reports for every ad account in
  scope — spend, clicks, impressions, conversions and conversion value — added up **within**
  the platform, converted with each day's rate, with the platform's own ROAS and cost per
  conversion. Conversions and conversion values are never added **across** platforms: the same
  sale is often claimed by both.
* **Per Google Analytics channel** (default channel group): sessions, engaged sessions, key
  events, purchases and purchase revenue of every property in scope, added up per channel.

The same availability rules as the registry: a day a source has not read makes that platform's
(or every channel's) figures "not synchronized"; never 0 for missing data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.advertising.models import AdPerformanceDaily
from app.domains.analytics.models import AnalyticsDaily
from app.domains.fx.service import FxTable
from app.domains.metrics.engine import (
    NOT_SYNCED,
    UNAVAILABLE,
    Figure,
    Scope,
    missing,
    plus,
    ratio,
    synced,
)


@dataclass(frozen=True)
class PlatformFigures:
    provider: str
    accounts: int
    figures: dict[str, Figure]


@dataclass(frozen=True)
class ChannelFigures:
    channel: str
    figures: dict[str, Figure]


def _days(first: date, last: date) -> list[date]:
    return [date.fromordinal(o) for o in range(first.toordinal(), last.toordinal() + 1)]


def _money(fx: FxTable, value: Decimal | None, currency: str, target: str, day: date) -> Figure:
    if value is None:
        return missing(UNAVAILABLE, "not_provided")
    converted = fx.convert(value, currency, target, day)
    return Figure(converted) if converted is not None else missing(UNAVAILABLE, "no_exchange_rate")


def _count(value: Decimal | int | None) -> Figure:
    return Figure(Decimal(value)) if value is not None else missing(UNAVAILABLE, "not_provided")


def platforms(
    session: Session, scope: Scope, first: date, last: date, fx: FxTable
) -> list[PlatformFigures]:
    accounts = list(scope.ad_accounts)
    if not accounts:
        return []
    rows = {
        (perf.ad_account_id, perf.day): perf
        for perf in session.execute(
            select(AdPerformanceDaily).where(
                AdPerformanceDaily.ad_account_id.in_([a.id for a in accounts]),
                AdPerformanceDaily.level == "account",
                AdPerformanceDaily.day.between(first, last),
            )
        ).scalars()
    }
    by_provider: dict[str, dict[str, list[Figure]]] = {}
    counts: dict[str, int] = {}
    for account in accounts:
        inputs = by_provider.setdefault(
            account.provider,
            {k: [] for k in ("spend", "clicks", "impressions", "conversions", "value")},
        )
        counts[account.provider] = counts.get(account.provider, 0) + 1
        for day in _days(first, last):
            perf = rows.get((account.id, day))
            if not synced(account, day) or perf is None:
                gap = missing(NOT_SYNCED, NOT_SYNCED)
                for values in inputs.values():
                    values.append(gap)
                continue
            inputs["spend"].append(_money(fx, perf.cost, account.currency, scope.currency, day))
            inputs["value"].append(
                _money(fx, perf.conversion_value, account.currency, scope.currency, day)
            )
            inputs["clicks"].append(_count(perf.clicks))
            inputs["impressions"].append(_count(perf.impressions))
            inputs["conversions"].append(_count(perf.conversions))
    found = []
    for provider, inputs in by_provider.items():
        spend, value = plus(*inputs["spend"]), plus(*inputs["value"])
        clicks, conversions = plus(*inputs["clicks"]), plus(*inputs["conversions"])
        found.append(
            PlatformFigures(
                provider,
                counts[provider],
                {
                    "spend": spend,
                    "clicks": clicks,
                    "impressions": plus(*inputs["impressions"]),
                    "conversions": conversions,
                    "conversion_value": value,
                    "platform_roas": ratio(value, spend, "no_ad_spend"),
                    "cost_per_click": ratio(spend, clicks, "no_clicks"),
                    "cost_per_conversion": ratio(spend, conversions, "no_conversions"),
                },
            )
        )
    return sorted(found, key=lambda p: p.provider)


def analytics_channels(
    session: Session, scope: Scope, first: date, last: date, fx: FxTable
) -> tuple[list[ChannelFigures], Figure | None]:
    """Google Analytics channels, most sessions first; the second value says why there are no
    channels (no property, or a day not read), else None."""
    props = list(scope.properties)
    if not props:
        return [], missing(UNAVAILABLE, "no_analytics_property")
    for prop in props:
        if not all(synced(prop, day) for day in _days(first, last)):
            return [], missing(NOT_SYNCED, NOT_SYNCED)
    currency_of = {p.id: p.currency for p in props}
    inputs: dict[str, dict[str, list[Figure]]] = {}
    for row in session.execute(
        select(AnalyticsDaily).where(
            AnalyticsDaily.property_id.in_(list(currency_of)),
            AnalyticsDaily.breakdown == "channel",
            AnalyticsDaily.day.between(first, last),
        )
    ).scalars():
        entry = inputs.setdefault(
            row.dimension_key,
            {k: [] for k in ("sessions", "engaged", "key_events", "purchases", "revenue")},
        )
        entry["sessions"].append(_count(row.sessions))
        entry["engaged"].append(_count(row.engaged_sessions))
        entry["key_events"].append(_count(row.key_events))
        entry["purchases"].append(_count(row.purchases))
        entry["revenue"].append(
            _money(fx, row.purchase_revenue, currency_of[row.property_id], scope.currency, row.day)
        )
    found = []
    for channel, entry in inputs.items():
        sessions, engaged = plus(*entry["sessions"]), plus(*entry["engaged"])
        found.append(
            ChannelFigures(
                channel,
                {
                    "sessions": sessions,
                    "engaged_sessions": engaged,
                    "engagement_rate": ratio(engaged, sessions, "no_sessions"),
                    "key_events": plus(*entry["key_events"]),
                    "purchases": plus(*entry["purchases"]),
                    "purchase_revenue": plus(*entry["revenue"]),
                },
            )
        )
    found.sort(key=lambda c: (-(c.figures["sessions"].value or 0), c.channel))
    return found, None
