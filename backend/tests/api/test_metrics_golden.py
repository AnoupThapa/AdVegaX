"""Golden datasets and property checks for ``analytics-v1`` (task 6-09, PLAN §11).

Dataset "Nepal" — worked out by hand. An organization reporting in NPR (Asia/Kathmandu) with
an NPR store, Meta in USD and Google Ads in EUR, 24 to 29 December 2025: Christmas (25, 26
December, no ECB rates), a weekend (27, 28) and a refund day (26). Nepal Rastra Bank publishes
USD on the 24th and 29th; it has no EUR here, so EUR goes through USD (EUR → USD by the ECB,
USD → NPR by the NRB).

==========  =========  ======  =======  ==========  ==========  ===========  ============
day         net sales  orders  cost     Meta (USD)  Google EUR  NPR per USD  EUR → USD
==========  =========  ======  =======  ==========  ==========  ===========  ============
24 Dec      10,000.00  4       6,000    10.00       8.00        133.50       1.04
25 Dec      (no sale)  0           0     5.00       0           (24th's)     (24th's)
26 Dec      -2,500.00  0       -1,500    5.00       0           (24th's)     (24th's)
27, 28 Dec  (no sale)  0           0     0          0           (24th's)     (24th's)
29 Dec       5,000.00  2       3,000    20.00       4.00        134.00       1.05
==========  =========  ======  =======  ==========  ==========  ===========  ============

Meta: 1,335.00 + 667.50 + 667.50 + 2,680.00 = 5,350.00 NPR.
Google: 8 x 1.04 x 133.50 = 1,110.72 and 4 x 1.05 x 134.00 = 562.80 → 1,673.52 NPR.
Ad spend 7,023.52 · net sales 12,500.00 · product cost 7,500.00 · gross profit 5,000.00 ·
profit after ad spend -2,023.52 (a loss, shown as such) · cost per order 7,023.52 / 6.
"""

from __future__ import annotations

import random
import time
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

import pytest
from app.domains.fx.service import FxTable
from app.domains.fx.sources import PublishedRate
from app.domains.metrics.engine import Figure, compute, load_inputs, load_scope
from sqlalchemy import text

from tests.api.test_metrics_engine import NOW, Seed
from tests.helpers import connected

SIX = Decimal("0.000001")
DEC = [date(2025, 12, d) for d in range(24, 30)]
D24, D25, D26, D27, D28, D29 = DEC


def _q(value: Decimal) -> Decimal:
    return value.quantize(SIX, rounding=ROUND_HALF_EVEN)


NEPAL_FX = FxTable(
    [
        PublishedRate("nrb", "USD", "NPR", D24, Decimal("133.50")),
        PublishedRate("nrb", "USD", "NPR", D29, Decimal("134.00")),
        PublishedRate("ecb", "EUR", "USD", D24, Decimal("1.04")),
        PublishedRate("ecb", "EUR", "USD", D29, Decimal("1.05")),
        PublishedRate("ecb", "EUR", "AUD", D24, Decimal("1.64")),
        PublishedRate("ecb", "EUR", "AUD", D29, Decimal("1.65")),
    ],
    timedelta(days=7),
)


def _org(make_client, admin_engine, name="Nepal Store"):
    c = make_client()
    c.signup(f"golden-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org(name)["id"]
    c.seed = Seed(admin_engine, c.org, connected(c, c.org))
    return c


def _metrics(runtime, org, first, last, *, currency, timezone, fx):
    with runtime.db.transaction(org_id=uuid.UUID(org.org)) as session:
        scope = load_scope(
            session,
            organization_id=uuid.UUID(org.org),
            currency=currency,
            timezone=timezone,
            now=NOW,
            store_id=None,
        )
        return load_inputs(session, scope, first, last, fx)


@pytest.fixture
def nepal(make_client, admin_engine):
    c = _org(make_client, admin_engine)
    c.seed.store(
        currency="NPR",
        tz="Asia/Kathmandu",
        days={
            D24: ("10000.00", 4, "6000.00"),
            D26: ("-2500.00", 0, "-1500.00"),
            D29: ("5000.00", 2, "3000.00"),
        },
    )
    c.seed.ad_account(
        "meta_ads",
        "USD",
        {D24: "10.00", D25: "5.00", D26: "5.00", D27: "0", D28: "0", D29: "20.00"},
    )
    google = dict.fromkeys(DEC, "0")  # a read day always has a row, zeros included
    c.seed.ad_account("google_ads", "EUR", {**google, D24: "8.00", D29: "4.00"})
    return c


def _nepal(runtime, org, first=D24, last=D29):
    return _metrics(
        runtime, org, first, last, currency="NPR", timezone="Asia/Kathmandu", fx=NEPAL_FX
    )


def test_nepal_golden_values_to_the_paisa(runtime, nepal):
    inputs = _nepal(runtime, nepal)
    m = compute(inputs.scope, inputs.period())
    assert m["net_sales"] == Figure(Decimal("12500.00"))
    assert m["orders"] == Figure(Decimal(6))
    assert m["product_cost"] == Figure(Decimal("7500.00"))
    assert m["gross_profit"] == Figure(Decimal("5000.00"))
    assert m["ad_spend"].value == Decimal("7023.52")
    assert m["profit_after_ad_spend"].value == Decimal("-2023.52")  # a loss, never hidden
    assert m["blended_roas"] == Figure(_q(Decimal("12500.00") / Decimal("7023.52")))
    assert m["cost_per_order"] == Figure(_q(Decimal("7023.52") / 6))
    assert m["sessions"].reason == "no_analytics_property"


def test_holidays_and_weekends_use_the_last_published_rate(runtime, nepal):
    inputs = _nepal(runtime, nepal)
    spend = [compute(inputs.scope, inputs.period(d, d))["ad_spend"].value for d in DEC]
    assert spend == [
        Decimal("2445.72"),  # 1,335.00 + 1,110.72
        Decimal("667.50"),  # Christmas: the 24th's rate
        Decimal("667.50"),
        Decimal(0),
        Decimal(0),
        Decimal("3242.80"),  # 2,680.00 + 562.80 at the 29th's rates
    ]


def test_a_refund_day_is_negative_not_hidden(runtime, nepal):
    inputs = _nepal(runtime, nepal)
    refund = compute(inputs.scope, inputs.period(D26, D26))
    assert refund["net_sales"] == Figure(Decimal("-2500.00"))
    assert refund["gross_profit"] == Figure(Decimal("-1000.00"))
    assert refund["blended_roas"] == Figure(_q(Decimal("-2500.00") / Decimal("667.50")))
    assert refund["cost_per_order"].reason == "no_orders"


def test_a_rate_older_than_seven_days_is_not_used(runtime, make_client, admin_engine):
    c = _org(make_client, admin_engine, "Stale")
    c.seed.store(currency="NPR", tz="Asia/Kathmandu", days={D24: ("100.00", 1, "40.00")})
    c.seed.ad_account("meta_ads", "USD", {date(2026, 1, 1): "1.00"})
    only_24th = FxTable(
        [PublishedRate("nrb", "USD", "NPR", D24, Decimal("133.50"))], timedelta(days=7)
    )
    jan1 = date(2026, 1, 1)  # 8 days after the last published rate
    inputs = _metrics(
        runtime, c, jan1, jan1, currency="NPR", timezone="Asia/Kathmandu", fx=only_24th
    )
    assert compute(inputs.scope, inputs.period())["ad_spend"] == Figure(
        None, "unavailable", "no_exchange_rate"
    )


def test_an_aud_business_over_christmas(runtime, make_client, admin_engine):
    """ECB only: USD → AUD is 1.64 / 1.04 from the 24th to the 28th, 1.65 / 1.05 on the 29th."""
    c = _org(make_client, admin_engine, "Christmas")
    c.seed.store(days={D24: ("1000.00", 5, "400.00")})
    c.seed.ad_account("meta_ads", "USD", dict.fromkeys(DEC, "10.40"))
    inputs = _metrics(
        runtime, c, D24, D29, currency="AUD", timezone="Australia/Sydney", fx=NEPAL_FX
    )
    days = [compute(inputs.scope, inputs.period(d, d))["ad_spend"].value for d in DEC]
    assert [round(v, 2) for v in days] == [Decimal("16.40")] * 5 + [Decimal("16.34")]


# ------------------------------------------------------------------ properties (PLAN §11)
ADDITIVE = ("net_sales", "orders", "product_cost", "gross_profit", "ad_spend", "sessions")


def test_totals_equal_the_sum_of_their_days(runtime, make_client, admin_engine):
    """For many random datasets, every additive figure of a period is the sum of its days."""
    rng = random.Random(6_09)
    c = _org(make_client, admin_engine, "Random")
    store_days, google, meta, sessions = {}, {}, {}, {}
    for d in DEC:
        if rng.random() < 0.8:
            net = Decimal(rng.randint(-50_000, 500_000)) / 100
            store_days[d] = (str(net), rng.randint(0, 20), str(abs(net) / 3))
        google[d] = str(Decimal(rng.randint(0, 20_000)) / 100)
        meta[d] = str(Decimal(rng.randint(0, 20_000)) / 100)
        sessions[d] = rng.randint(0, 5_000)
    c.seed.store(days=store_days)
    c.seed.ad_account("google_ads", "AUD", google)
    c.seed.ad_account("meta_ads", "USD", meta)
    c.seed.analytics_property(sessions)
    inputs = _metrics(
        runtime, c, D24, D29, currency="AUD", timezone="Australia/Sydney", fx=NEPAL_FX
    )
    total = compute(inputs.scope, inputs.period())
    by_day = [compute(inputs.scope, inputs.period(d, d)) for d in DEC]
    for key in ADDITIVE:
        assert total[key].value == sum((day[key].value for day in by_day), Decimal(0)), key
    for first in range(len(DEC)):
        for last in range(first, len(DEC)):
            part = compute(inputs.scope, inputs.period(DEC[first], DEC[last]))
            expected = sum((by_day[i]["net_sales"].value for i in range(first, last + 1)), 0)
            assert part["net_sales"].value == expected


def test_converting_and_converting_back_stays_within_one_minor_unit():
    rng = random.Random(42)
    cent = Decimal("0.01")
    for _ in range(2_000):
        day = date(2026, 3, rng.randint(2, 6))
        aud, usd = (Decimal(rng.randint(5_000, 25_000)) / 10_000 for _ in range(2))
        npr = Decimal(rng.randint(10_000, 20_000)) / 100
        fx = FxTable(
            [
                PublishedRate("ecb", "EUR", "AUD", day, aud),
                PublishedRate("ecb", "EUR", "USD", day, usd),
                PublishedRate("nrb", "USD", "NPR", day, npr),
            ],
            timedelta(days=7),
        )
        amount = Decimal(rng.randint(1, 10_000_000)) / 100
        for a, b in (("AUD", "USD"), ("NPR", "AUD"), ("USD", "NPR"), ("EUR", "NPR")):
            there = fx.convert(amount, a, b, day)
            assert there is not None
            back = fx.convert(there, b, a, day)
            assert back is not None
            assert abs(back.quantize(cent, rounding=ROUND_HALF_EVEN) - amount) <= cent, (a, b)


# ------------------------------------------------------------------ performance (Q-6-13)
def test_a_large_organization_is_read_quickly(runtime, make_client, admin_engine):
    """5 stores, 10 ad accounts and 5 properties with 390 days each, read for 390 days: the
    figures are computed on read; this records the time (PHASE_06_REPORT, Q-6-13)."""
    c = _org(make_client, admin_engine, "Large")
    days = [date(2025, 9, 16) + timedelta(days=i) for i in range(390)]
    for _ in range(5):
        c.seed.store(days=dict.fromkeys(days, ("1234.56", 12, "500.00")))
        c.seed.analytics_property(dict.fromkeys(days, 900))
    for i in range(10):
        c.seed.ad_account(
            "meta_ads" if i % 2 else "google_ads",
            "USD" if i % 2 else "AUD",
            dict.fromkeys(days, "45.67"),
        )
    with admin_engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO fx_rates (source, base, quote, rate_date, rate, fetched_at) "
                "SELECT 'ecb', 'EUR', q, d::date, r, now() FROM generate_series("
                "'2025-09-08'::date, '2026-10-20'::date, '1 day') AS d, "
                "(VALUES ('AUD', 1.6), ('USD', 1.1)) AS v(q, r) ON CONFLICT DO NOTHING"
            )
        )
    c.patch(f"/organizations/{c.org}", {"default_timezone": "Australia/Sydney"})
    started = time.perf_counter()
    response = c.get(f"/organizations/{c.org}/analytics/overview?from={days[0]}&to={days[-1]}")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert len(data["days"]) == 390
    assert data["totals"]["net_sales"]["value"] is not None
    print(f"\n390-day overview, 5 stores / 10 ad accounts / 5 properties: {elapsed:.2f} s")
    assert elapsed < 15  # generous for CI machines; measured times are in PHASE_06_REPORT


# ------------------------------------------------------------------ computed on read (criterion 3)
def test_a_correction_changes_every_report_at_once(make_client, admin_engine):
    """A late refund (the store's daily figures re-derived), a Google correction (a day read
    again) and a product cost edit show in the next answer, with no recomputation step."""
    c = _org(make_client, admin_engine, "Corrections")
    day = date(2026, 10, 5)
    store = c.seed.store(days={day: ("1000.00", 10, "400.00")})
    account = c.seed.ad_account("google_ads", "AUD", {day: "100.00"})
    path = f"/organizations/{c.org}/analytics/overview?from={day}&to={day}"

    def totals():
        response = c.get(path)
        assert response.status_code == 200, response.text
        t = response.json()["data"]["totals"]
        return tuple(Decimal(t[k]["value"]) for k in ("net_sales", "gross_profit", "ad_spend"))

    assert totals() == (Decimal(1000), Decimal(600), Decimal(100))
    with admin_engine.begin() as db:
        db.execute(
            text("UPDATE financial_daily SET net_sales = 900, cogs = 380 WHERE store_id = :s"),
            {"s": store},
        )  # a late refund and a cost edit, re-derived by the finance engine
        db.execute(
            text("UPDATE ad_performance_daily SET cost = 90 WHERE ad_account_id = :a"),
            {"a": account},
        )  # Google corrected the day
    assert totals() == (Decimal(900), Decimal(520), Decimal(90))
