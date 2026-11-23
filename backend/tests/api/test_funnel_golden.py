# ruff: noqa: F401, F811 (fixtures shared with test_funnel_engine / test_unified_analytics_api)
"""Golden funnel datasets, property checks and reconciliation (task 7-08, PLAN §11, §13).

Dataset "drop-off", worked out by hand: a Google Analytics property and a store over 120 days
to 13 October 2026. Every day 100 visits → 40 product views → 10 adds to cart → 5 checkouts →
2 purchases, and the store takes 2 orders. In the last 7 days (7 to 13 October) adds to cart fall
to 6 a day: 6 / 40 = 15 % of product views, against 25 % in the previous 7 days and 25 % on
average over the 90 days before — a 40 % fall with 280 product views before it, so it is a
finding (Q-7-7). Checkouts per add to cart stay at 50 %, so they are not.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from app.domains.funnel.engine import load_funnel, whole
from app.domains.metrics.engine import load_inputs, load_scope
from sqlalchemy import text

from tests.api.test_funnel_api import _campaign, _ids, _source_row
from tests.api.test_funnel_engine import D5, D6, FX, NOW, golden, org
from tests.api.test_metrics_engine import Seed
from tests.api.test_unified_analytics_api import rates
from tests.helpers import connected

LAST = date(2026, 10, 13)
FIRST = LAST - timedelta(days=6)


def _v(figure):
    return None if figure["value"] is None else Decimal(figure["value"])


@pytest.fixture
def steady(make_client, admin_engine):
    c = make_client()
    c.signup(f"drop-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Drop Co")["id"]
    seed = Seed(admin_engine, c.org, connected(c, c.org))
    days = [LAST - timedelta(days=n) for n in range(120)]
    seed.store(days=dict.fromkeys(days, ("100.00", 2, "40.00")))
    prop = seed.analytics_property(dict.fromkeys(days, 100))
    with admin_engine.begin() as db:
        db.execute(
            text(
                "UPDATE analytics_daily SET item_view_events = 40, purchases = 2, "
                "add_to_carts = CASE WHEN day >= :first THEN 6 ELSE 10 END, "
                "checkouts = CASE WHEN day >= :first THEN 3 ELSE 5 END "
                "WHERE property_id = :prop"
            ),
            {"first": FIRST, "prop": prop},
        )
    c.prop = prop
    return c


def test_a_real_drop_off_is_found_through_the_api(steady):
    response = steady.get(f"/organizations/{steady.org}/analytics/funnel?from={FIRST}&to={LAST}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [_v(data["stages"][k]) for k in ("landing_page_views", "product_views")] == [
        Decimal(700),
        Decimal(280),
    ]
    (finding,) = data["findings"]
    assert (finding["view"], finding["from_stage"], finding["to_stage"]) == (
        "whole",
        "product_views",
        "adds_to_cart",
    )
    assert (finding["rate"], finding["previous_rate"], finding["baseline_rate"]) == (
        "0.150000",
        "0.250000",
        "0.250000",
    )
    assert (Decimal(finding["events_before"]), finding["change"]) == (Decimal(280), "-0.4000")
    assert (data["rules"]["previous_from"], data["rules"]["previous_to"]) == (
        "2026-09-30",
        "2026-10-06",
    )


def test_the_previous_week_itself_had_no_drop(steady):
    start, end = FIRST - timedelta(days=7), FIRST - timedelta(days=1)
    response = steady.get(f"/organizations/{steady.org}/analytics/funnel?from={start}&to={end}")
    assert response.json()["data"]["findings"] == []


# ------------------------------------------------------------------ reconciliation (§13, 6)
@pytest.fixture
def owner(golden, rates):
    return golden


def test_the_funnel_reconciles_with_the_overview_and_the_property_page(owner):
    period = f"?from={D5}&to={D6}"
    funnel = owner.get(f"/organizations/{owner.org}/analytics/funnel{period}").json()["data"]
    overview = owner.get(f"/organizations/{owner.org}/analytics/overview{period}").json()["data"]
    assert _v(funnel["stages"]["purchases"]) == _v(overview["totals"]["orders"])
    assert _v(funnel["stages"]["landing_page_views"]) == _v(overview["totals"]["sessions"])
    assert _v(funnel["stages"]["analytics_purchases"]) == _v(
        overview["totals"]["analytics_purchases"]
    )
    page = owner.get(
        f"/organizations/{owner.org}/analytics-properties/{owner.prop}/metrics/daily{period}"
    ).json()["data"]["totals"]
    assert _v(funnel["stages"]["landing_page_views"]) == Decimal(page["sessions"])
    channels = owner.get(f"/organizations/{owner.org}/analytics/channels{period}").json()["data"]
    meta = next(p for p in channels["platforms"] if p["provider"] == "meta_ads")
    funnel_meta = next(p for p in funnel["platforms"] if p["provider"] == "meta_ads")
    assert _v(funnel_meta["stages"]["clicks"]) == _v(meta["figures"]["clicks"])
    assert _v(funnel_meta["stages"]["impressions"]) == _v(meta["figures"]["impressions"])


# ------------------------------------------------------------------ properties (§11)
def test_stage_totals_equal_the_sum_of_their_days(runtime, golden, admin_engine):
    rng = random.Random(708)
    with admin_engine.begin() as db:
        for day in (D5, D6):
            db.execute(
                text(
                    "UPDATE analytics_daily SET sessions = :n, item_view_events = :v, "
                    "add_to_carts = :c, checkouts = :k, purchases = :p "
                    "WHERE property_id = :prop AND day = :d AND breakdown = 'total'"
                ),
                {
                    "n": rng.randint(0, 900),
                    "v": rng.randint(0, 400),
                    "c": rng.randint(0, 90),
                    "k": rng.randint(0, 40),
                    "p": rng.randint(0, 20),
                    "prop": golden.prop,
                    "d": day,
                },
            )
    with runtime.db.transaction(org_id=uuid.UUID(golden.org)) as session:
        scope = load_scope(
            session,
            organization_id=uuid.UUID(golden.org),
            currency="AUD",
            timezone="Australia/Sydney",
            now=NOW,
        )
        funnel = load_funnel(session, scope, load_inputs(session, scope, D5, D6, FX))
    total, _ = whole(scope, funnel.period())
    days = [whole(scope, funnel.period(d, d))[0] for d in (D5, D6)]
    for key, figure in total.items():
        if figure.ok:
            assert figure.value == sum((d[key].value for d in days), Decimal(0)), key


def test_campaigns_and_other_traffic_always_add_up_to_the_website(owner, admin_engine):
    rng = random.Random(7)
    accounts = _ids(admin_engine, owner.org)
    names = ["Spring", "Gloves", "Masks", "Brand"]
    with admin_engine.begin() as db:
        for name in names:
            _campaign(db, owner.org, accounts["meta_ads"], name, [])
            _campaign(db, owner.org, accounts["google_ads"], name, [])
        seen: set[tuple[object, ...]] = set()
        for _ in range(40):
            source, medium = rng.choice(
                [
                    ("facebook", "paid"),
                    ("instagram", "cpc"),
                    ("google", "cpc"),
                    ("google", "organic"),
                    ("bing", "cpc"),
                ]
            )
            campaign, day = rng.choice([*names, "(organic)", "Other"]), rng.choice((D5, D6))
            if (source, medium, campaign, day) in seen:
                continue  # one row per source / medium / campaign and day, as Google sends
            seen.add((source, medium, campaign, day))
            n = rng.randint(1, 50)
            _source_row(
                db,
                owner.prop,
                day,
                source,
                medium,
                campaign,
                n,
                rng.randint(0, n),
                rng.randint(0, 10),
                rng.randint(0, 5),
                rng.randint(0, 3),
            )
    data = owner.get(f"/organizations/{owner.org}/analytics/funnel/campaigns?from={D5}&to={D6}")
    data = data.json()["data"]
    counted: set[tuple[str, str]] = set()
    for key in data["website"]:
        matched = Decimal(0)
        counted.clear()
        for c in data["items"]:
            group = ("google" if c["provider"] == "google_ads" else "meta", c["name"])
            if c["analytics"][key]["value"] is None or group in counted:
                continue  # no match, or a match shared with a campaign already counted
            counted.add(group)
            matched += _v(c["analytics"][key])
        assert matched + _v(data["other_traffic"][key]) == _v(data["website"][key]), key
