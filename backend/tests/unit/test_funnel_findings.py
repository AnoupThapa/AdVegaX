"""Drop-off findings (task 7-05, PLAN Q-7-7): fixed rules, a business compared with itself.

The data: 120 days of a steady funnel — 100 sessions → 40 product views → 10 adds to cart →
5 checkouts → 2 purchases a day; Meta 1,000 impressions → 30 clicks. In the last 7 days adds to
cart fall to 6 a day (25 % → 15 % of product views: 40 % lower than the previous 7 days and
below the 90-day average). Product views in the period: 280 (≥ 200).
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
from app.core.settings import get_settings
from app.domains.funnel.engine import FunnelDay, FunnelInputs
from app.domains.funnel.findings import Rules, find_drop_offs, rules_from
from app.domains.metrics.engine import NOT_SYNCED, Figure, Scope, Source, missing

LAST = date(2026, 10, 14)
FIRST = LAST - timedelta(days=6)
START = LAST - timedelta(days=119)
RULES = Rules(drop_share=Decimal("0.25"), min_events=200, baseline_days=90)


def _source(kind, provider):
    return Source(kind, uuid.uuid4(), provider, kind, "AUD", "Australia/Sydney", START, LAST)


SCOPE = Scope(
    currency="AUD",
    timezone="Australia/Sydney",
    stores=(_source("store", "shopify"),),
    ad_accounts=(_source("ad_account", "meta_ads"),),
    properties=(_source("analytics_property", "google_analytics"),),
    every_store_measured=True,
)


def _day(carts=10, *, gap=False, meta_clicks=30):
    d = FunnelDay()
    f = (lambda _v: missing(NOT_SYNCED, NOT_SYNCED)) if gap else (lambda v: Figure(Decimal(v)))
    d.ads["impressions"].append(f(1000))
    d.ads["clicks"].append(f(meta_clicks))
    for stage, value in (
        ("landing_page_views", 100),
        ("product_views", 40),
        ("adds_to_cart", carts),
        ("checkouts", carts // 2),
        ("analytics_purchases", 2),
    ):
        d.analytics[stage].append(f(value))
    for stage, value in (
        ("impressions", 1000),
        ("clicks", meta_clicks),
        ("landing_page_views", 25),
        ("product_views", 20),
        ("adds_to_cart", 5),
        ("checkouts", 3),
        ("purchases", 2),
    ):
        d.platforms["meta_ads"][stage].append(f(value))
    d.orders.append(f(2))
    return d


def _funnel(current=None, previous=None, start=START):
    days = {}
    day = start
    while day <= LAST:
        if day >= FIRST:
            days[day] = (current or _day)()
        elif day >= FIRST - timedelta(days=7):
            days[day] = (previous or _day)()
        else:
            days[day] = _day()
        day += timedelta(days=1)
    return FunnelInputs(SCOPE, start, LAST, days)


def test_a_clear_drop_is_found_with_its_numbers():
    (found,) = find_drop_offs(SCOPE, _funnel(lambda: _day(carts=6)), FIRST, LAST, RULES)
    assert (found.view, found.subject, found.from_stage, found.to_stage) == (
        "whole",
        None,
        "product_views",
        "adds_to_cart",
    )
    assert (found.rate, found.previous_rate, found.baseline_rate) == (
        Decimal("0.150000"),
        Decimal("0.250000"),
        Decimal("0.250000"),
    )
    assert (found.events_before, found.change) == (Decimal(280), Decimal("-0.4000"))


def test_a_steady_funnel_has_no_findings():
    assert find_drop_offs(SCOPE, _funnel(), FIRST, LAST, RULES) == []


def test_a_small_drop_is_not_a_finding():
    # 25 % → 20 %: 20 % lower, below the 25 % rule
    assert find_drop_offs(SCOPE, _funnel(lambda: _day(carts=8)), FIRST, LAST, RULES) == []


def test_small_numbers_never_alarm():
    rules = replace(RULES, min_events=1000)  # 280 product views is not enough
    assert find_drop_offs(SCOPE, _funnel(lambda: _day(carts=6)), FIRST, LAST, rules) == []


def test_a_fall_that_stays_above_the_usual_level_is_not_a_finding():
    # an unusually good previous week (50 %), then 27.5 %: 45 % lower, but still above the
    # 90-day average (about 26.9 %)
    funnel = _funnel(lambda: _day(carts=11), lambda: _day(carts=20))
    assert find_drop_offs(SCOPE, funnel, FIRST, LAST, RULES) == []


def test_a_platforms_own_drop_is_found_per_platform():
    found = find_drop_offs(SCOPE, _funnel(lambda: _day(meta_clicks=15)), FIRST, LAST, RULES)
    keys = {(f.view, f.subject, f.from_stage, f.to_stage) for f in found}
    assert ("platform", "meta_ads", "impressions", "clicks") in keys
    assert ("whole", None, "impressions", "clicks") in keys
    # clicks → landing page views crosses sources: never judged
    assert not any(f.to_stage == "landing_page_views" and f.view == "whole" for f in found)


def test_missing_days_are_never_flagged():
    gap_week = _funnel(lambda: _day(carts=6), lambda: _day(gap=True))
    assert find_drop_offs(SCOPE, gap_week, FIRST, LAST, RULES) == []
    current_gap = _funnel(lambda: _day(carts=6, gap=True))
    assert find_drop_offs(SCOPE, current_gap, FIRST, LAST, RULES) == []


def test_without_the_history_before_the_period_nothing_is_judged():
    short = _funnel(lambda: _day(carts=6), start=FIRST - timedelta(days=7))
    assert find_drop_offs(SCOPE, short, FIRST, LAST, RULES) == []


@pytest.mark.parametrize("carts", [6, 7])
def test_findings_are_ordered_by_the_largest_fall(carts):
    found = find_drop_offs(
        SCOPE, _funnel(lambda: _day(carts=carts, meta_clicks=10)), FIRST, LAST, RULES
    )
    assert [f.change for f in found] == sorted(f.change for f in found)


def test_the_rules_come_from_settings():
    assert rules_from(get_settings()) == RULES
