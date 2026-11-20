"""The funnel, ``funnel-v1`` (task 7-04, PLAN §6, Q-7-1 … Q-7-5).

Golden dataset, worked out by hand: one AUD store, Google Ads (AUD), Meta (USD) and a Google
Analytics property, 5 and 6 October 2026.

==========  ======  ======  ===============================  =========================  ======
day         Google  Google  Meta: impr / clicks / lpv /      GA4: sessions / views /    store
            impr    clicks  views / carts / checkouts / buys  carts / checkouts / buys   orders
==========  ======  ======  ===============================  =========================  ======
5 Oct       1,000   50 (2)  2,000 / 40 / 30 / 20 / 8 / 4 / 3  300 / 120 / 30 / 12 / 6    10
6 Oct         800   30 (1)  1,000 / 20 / 15 / 10 / 4 / 2 / 1  200 /  80 / 20 /  8 / 4     5
==========  ======  ======  ===============================  =========================  ======

Whole business: impressions 4,800 → clicks 140 (CTR 140 / 4,800) → [different sources] →
landing page views 500 → product views 200 (0.4) → adds to cart 50 (0.25) → checkouts 20
(0.4) → GA purchases 10 (0.5); store orders 15, store conversion 15 / 500 = 0.03.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from app.domains.funnel.engine import channels, load_funnel, platforms, whole
from app.domains.funnel.registry import FUNNEL_VERSION, STAGES, STEPS
from app.domains.metrics.engine import Figure, load_inputs, load_scope
from sqlalchemy import text

from tests.api.test_metrics_engine import D5, D6, FX, NOW, Seed
from tests.helpers import connected


def _q(numerator, denominator):
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.000001"))


def _account(db, org, account, day, impressions, clicks, purchases, funnel=None):
    lpv, views, carts, checkouts = funnel or (None, None, None, None)
    db.execute(
        text(
            "INSERT INTO ad_performance_daily (id, organization_id, ad_account_id, level, "
            "entity_key, day, impressions, clicks, cost, conversions, conversion_value, "
            "landing_page_views, content_views, adds_to_cart, checkouts_initiated, currency, "
            "fetched_at) SELECT gen_random_uuid(), :org, :acc, 'account', 'account', :day, :imp, "
            ":clk, 1, :buys, 0, :lpv, :views, :carts, :checkouts, currency, now() "
            "FROM ad_accounts WHERE id = :acc"
        ),
        {
            "org": org,
            "acc": account,
            "day": day,
            "imp": impressions,
            "clk": clicks,
            "buys": Decimal(purchases),
            "lpv": lpv,
            "views": views,
            "carts": carts,
            "checkouts": checkouts,
        },
    )


def _visits(db, prop, day, sessions, views, carts, checkouts, purchases, channel=None):
    params = {
        "prop": prop,
        "day": day,
        "n": sessions,
        "v": views,
        "c": carts,
        "k": checkouts,
        "p": purchases,
        "ch": channel,
    }
    if channel is None:
        db.execute(
            text(
                "UPDATE analytics_daily SET sessions = :n, item_view_events = :v, "
                "add_to_carts = :c, checkouts = :k, purchases = :p "
                "WHERE property_id = :prop AND day = :day AND breakdown = 'total'"
            ),
            params,
        )
        return
    db.execute(
        text(
            "INSERT INTO analytics_daily (id, organization_id, property_id, day, breakdown, "
            "dimension_key, channel_group, sessions, engaged_sessions, total_users, new_users, "
            "key_events, purchases, purchase_revenue, item_view_events, add_to_carts, "
            "checkouts, currency, fetched_at) SELECT gen_random_uuid(), organization_id, id, "
            ":day, 'channel', :ch, :ch, :n, 0, 0, 0, 0, :p, 0, :v, :c, :k, currency, now() "
            "FROM analytics_properties WHERE id = :prop"
        ),
        params,
    )


@pytest.fixture
def org(make_client, admin_engine):
    c = make_client()
    c.signup(f"funnel-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    c.seed = Seed(admin_engine, c.org, connected(c, c.org))
    return c


@pytest.fixture
def golden(org, admin_engine):
    s = org.seed
    org.store_id = s.store(days={D5: ("1000.00", 10, "400.00"), D6: ("500.50", 5, "200.20")})
    google = s.ad_account("google_ads", "AUD", {})
    meta = s.ad_account("meta_ads", "USD", {})
    prop = s.analytics_property({D5: 0, D6: 0})
    with admin_engine.begin() as db:
        _account(db, org.org, google, D5, 1000, 50, 2)
        _account(db, org.org, google, D6, 800, 30, 1)
        _account(db, org.org, meta, D5, 2000, 40, 3, (30, 20, 8, 4))
        _account(db, org.org, meta, D6, 1000, 20, 1, (15, 10, 4, 2))
        _visits(db, prop, D5, 300, 120, 30, 12, 6)
        _visits(db, prop, D6, 200, 80, 20, 8, 4)
        _visits(db, prop, D5, 100, 50, 10, 5, 3, channel="Paid Search")
        _visits(db, prop, D5, 200, 70, 20, 7, 3, channel="Organic Search")
        _visits(db, prop, D6, 120, 60, 12, 6, 3, channel="Paid Search")
        _visits(db, prop, D6, 80, 20, 8, 2, 1, channel="Organic Search")
    org.prop = prop
    return org


def _funnel(runtime, c, first=D5, last=D6, store_id=None):
    with runtime.db.transaction(org_id=uuid.UUID(c.org)) as session:
        scope = load_scope(
            session,
            organization_id=uuid.UUID(c.org),
            currency="AUD",
            timezone="Australia/Sydney",
            now=NOW,
            store_id=uuid.UUID(store_id) if store_id else None,
        )
        funnel = load_funnel(session, scope, load_inputs(session, scope, first, last, FX))
    return scope, funnel


def _value(figure):
    return figure.value


# ------------------------------------------------------------------ the whole business
def test_the_golden_funnel(runtime, golden):
    scope, funnel = _funnel(runtime, golden)
    stages, steps = whole(scope, funnel.period())
    assert {k: _value(v) for k, v in stages.items()} == {
        "impressions": Decimal(4800),
        "clicks": Decimal(140),
        "landing_page_views": Decimal(500),
        "product_views": Decimal(200),
        "adds_to_cart": Decimal(50),
        "checkouts": Decimal(20),
        "purchases": Decimal(15),
        "analytics_purchases": Decimal(10),
    }
    rates = {(s.step.from_stage, s.step.to_stage): s.rate for s in steps}
    assert rates[("impressions", "clicks")] == Figure(_q(140, 4800))
    assert rates[("clicks", "landing_page_views")] is None  # different sources: no rate
    assert rates[("landing_page_views", "product_views")] == Figure(Decimal("0.400000"))
    assert rates[("product_views", "adds_to_cart")] == Figure(Decimal("0.250000"))
    assert rates[("adds_to_cart", "checkouts")] == Figure(Decimal("0.400000"))
    assert rates[("checkouts", "analytics_purchases")] == Figure(Decimal("0.500000"))
    assert rates[("landing_page_views", "purchases")] == Figure(Decimal("0.030000"))


def test_each_day_has_its_own_funnel(runtime, golden):
    scope, funnel = _funnel(runtime, golden)
    sixth, _ = whole(scope, funnel.period(D6, D6))
    assert (_value(sixth["clicks"]), _value(sixth["adds_to_cart"])) == (Decimal(50), Decimal(20))


def test_each_platform_reports_its_own_funnel(runtime, golden):
    scope, funnel = _funnel(runtime, golden)
    (google, google_accounts, g, g_steps), (meta, _, m, m_steps) = platforms(scope, funnel.period())
    assert (google, google_accounts, meta) == ("google_ads", 1, "meta_ads")
    assert (_value(g["impressions"]), _value(g["clicks"]), _value(g["purchases"])) == (
        Decimal(1800),
        Decimal(80),
        Decimal(3),
    )
    assert g["adds_to_cart"] == Figure(None, "unsupported", "not_provided_by_platform")
    assert [(s.step.from_stage, s.step.to_stage) for s in g_steps] == [
        ("impressions", "clicks"),
        ("clicks", "purchases"),
    ]
    assert g_steps[1].rate == Figure(_q(3, 80))
    assert [_value(m[k]) for k in m] == [
        Decimal(3000),
        Decimal(60),
        Decimal(45),
        Decimal(30),
        Decimal(12),
        Decimal(6),
        Decimal(4),
    ]
    assert len(m_steps) == 6 and m_steps[-1].rate == Figure(_q(4, 6))


def test_google_analytics_channels_most_sessions_first(runtime, golden):
    scope, funnel = _funnel(runtime, golden)
    found, why = channels(scope, funnel.period())
    assert why is None
    assert [name for name, _, _ in found] == ["Organic Search", "Paid Search"]
    _, paid, paid_steps = found[1]
    assert (_value(paid["landing_page_views"]), _value(paid["adds_to_cart"])) == (
        Decimal(220),
        Decimal(22),
    )
    assert paid_steps[0].rate == Figure(_q(110, 220))  # product views / sessions


# ------------------------------------------------------------------ never 0 for missing data
def test_a_day_not_read_is_not_synchronized(runtime, golden):
    scope, funnel = _funnel(runtime, golden, first=date(2025, 9, 1), last=D5)
    stages, steps = whole(scope, funnel.period())
    for key in ("impressions", "landing_page_views", "purchases"):
        assert stages[key] == Figure(None, "not_synchronized", "not_synchronized"), key
    assert steps[0].rate.availability == "not_synchronized"
    assert channels(scope, funnel.period())[1].availability == "not_synchronized"


def test_figures_not_reread_yet_are_not_synchronized(runtime, golden, admin_engine):
    with admin_engine.begin() as db:
        db.execute(text("UPDATE analytics_daily SET add_to_carts = NULL WHERE day = :d"), {"d": D6})
        db.execute(
            text("UPDATE ad_performance_daily SET content_views = NULL WHERE day = :d"), {"d": D6}
        )
    scope, funnel = _funnel(runtime, golden)
    stages, _ = whole(scope, funnel.period())
    assert stages["adds_to_cart"].availability == "not_synchronized"
    assert stages["product_views"].ok  # other stages are unaffected
    meta = platforms(scope, funnel.period())[1][2]
    assert meta["product_views"].availability == "not_synchronized"


def test_a_property_without_ecommerce_events_says_so(runtime, golden, admin_engine):
    with admin_engine.begin() as db:
        db.execute(
            text("UPDATE analytics_daily SET item_view_events = 0, add_to_carts = 0, checkouts = 0")
        )
    scope, funnel = _funnel(runtime, golden)
    stages, steps = whole(scope, funnel.period())
    assert stages["adds_to_cart"] == Figure(None, "unavailable", "no_events_reported")
    assert stages["landing_page_views"].ok
    assert next(s for s in steps if s.step.to_stage == "product_views").rate.reason == (
        "no_events_reported"
    )


def test_nothing_connected_of_a_kind_says_so(runtime, org):
    org.seed.store(days={D5: ("100.00", 2, "40.00")})
    scope, funnel = _funnel(runtime, org, first=D5, last=D5)
    stages, steps = whole(scope, funnel.period())
    assert stages["impressions"] == Figure(None, "unavailable", "no_ad_account")
    assert stages["landing_page_views"] == Figure(None, "unavailable", "no_analytics_property")
    assert stages["purchases"] == Figure(Decimal(2))
    assert steps[-1].rate.reason == "not_every_store_measured"
    assert platforms(scope, funnel.period()) == []
    assert channels(scope, funnel.period()) == (
        [],
        Figure(None, "unavailable", "no_analytics_property"),
    )


def test_zero_earlier_stage_names_itself(runtime, golden, admin_engine):
    with admin_engine.begin() as db:
        db.execute(text("UPDATE ad_performance_daily SET impressions = 0, clicks = 0"))
    scope, funnel = _funnel(runtime, golden)
    _, steps = whole(scope, funnel.period())
    assert steps[0].rate == Figure(None, "unavailable", "no_impressions")


# ------------------------------------------------------------------ the registry
def test_every_stage_and_step_is_defined_once():
    assert FUNNEL_VERSION == "funnel-v1"
    keys = [s.key for s in STAGES]
    assert len(keys) == len(set(keys))
    assert all(s.formula and s.label for s in STAGES)
    for step in STEPS:
        assert {step.from_stage, step.to_stage} <= set(keys)
    sources = {s.key: s.source for s in STAGES}
    for step in STEPS:  # a rate only between stages of the same source (Q-7-2)
        same = sources[step.from_stage] == sources[step.to_stage]
        assert (step.kind == "same_source") == same or step.kind == "store_conversion"
