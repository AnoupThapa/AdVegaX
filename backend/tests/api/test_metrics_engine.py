"""The unified metrics, ``analytics-v1`` (task 6-04, PLAN §6, Q-6-1 … Q-6-12).

Golden dataset, worked out by hand: one AUD store (Sydney), Google Ads in AUD, Meta in USD and
a Google Analytics property, 5 to 7 October 2026. The ECB publishes on the 5th and 6th; the 7th
uses the 6th's rate (as for a holiday).

==========  =========  ======  =======  ===========  ==========  ==========  ========
day         net sales  orders  cost     Google (AUD) Meta (USD)  USD → AUD   sessions
==========  =========  ======  =======  ===========  ==========  ==========  ========
5 Oct       1,000.00   10      400.00   100.00       20.00       1.6         300
6 Oct         500.50    5      200.20    50.00       10.00       1.5         200
7 Oct       (no sale)   0        0.00     0.00        5.00       1.5         100
total       1,500.50   15      600.20   150.00       35.00 → 54.50           600
==========  =========  ======  =======  ===========  ==========  ==========  ========

Ad spend 204.50 · gross profit 900.30 · profit after ad spend 695.80 · blended ROAS
1,500.50 / 204.50 · cost per order 204.50 / 15 · store conversion rate 15 / 600 = 0.025.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

import pytest
from app.domains.fx.service import FxTable
from app.domains.fx.sources import PublishedRate
from app.domains.metrics.engine import Figure, compute, load_inputs, load_scope
from app.domains.metrics.registry import BY_KEY, DEFINITION_VERSION, METRICS
from sqlalchemy import text

from tests.helpers import connected

D5, D6, D7 = date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)
NOW = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)
SIX = Decimal("0.000001")


def _q(value: str | Decimal) -> Decimal:
    return Decimal(value).quantize(SIX, rounding=ROUND_HALF_EVEN)


FX = FxTable(
    [
        PublishedRate("ecb", "EUR", "AUD", D5, Decimal("1.6")),
        PublishedRate("ecb", "EUR", "USD", D5, Decimal("1.0")),
        PublishedRate("ecb", "EUR", "AUD", D6, Decimal("1.65")),
        PublishedRate("ecb", "EUR", "USD", D6, Decimal("1.1")),
    ],
    timedelta(days=7),
)


FINANCIAL = (
    "INSERT INTO financial_daily (id, organization_id, store_id, day, currency, "
    "definition_version, gross_sales, discounts, sales_reversals, net_sales, shipping, taxes, "
    "duties, fees, total_sales, orders_count, cogs, costed_net_sales, uncosted_lines, "
    "other_currency_orders, computed_at) VALUES (gen_random_uuid(), :org, :store, :day, :cur, "
    "'finance-v1', :net, 0, 0, :net, 0, 0, 0, 0, :net, :orders, :cogs, :net, :uncosted, :other, "
    "now())"
)


class Seed:
    """Writes sources and their daily rows straight into the database (as the imports do)."""

    def __init__(self, admin_engine, org: str, connection: str) -> None:
        self.db, self.org, self.conn = admin_engine, org, connection

    def _resource(self, db, kind: str) -> str:
        rid = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO external_resources (id, organization_id, connection_id, kind, "
                "provider, external_id, discovered_at, last_seen_at) VALUES (:id, :org, :conn, "
                ":kind, 'fake', :ext, now(), now())"
            ),
            {"id": rid, "org": self.org, "conn": self.conn, "kind": kind, "ext": rid},
        )
        return rid

    def store(self, currency="AUD", tz="Australia/Sydney", days=None, imported=True) -> str:
        sid = str(uuid.uuid4())
        with self.db.begin() as db:
            db.execute(
                text(
                    "INSERT INTO stores (id, organization_id, external_resource_id, provider, "
                    "external_store_id, domain, currency, timezone, history_from, "
                    "first_import_completed_at) VALUES (:id, :org, :res, 'fake', :ext, :dom, "
                    ":cur, :tz, '2025-09-13T00:00:00Z', :done)"
                ),
                {
                    "id": sid,
                    "ext": sid,
                    "org": self.org,
                    "res": self._resource(db, "store"),
                    "dom": f"{sid[:8]}.example",
                    "cur": currency,
                    "tz": tz,
                    "done": NOW if imported else None,
                },
            )
            for day, (net, orders, cogs, *other) in (days or {}).items():
                db.execute(
                    text(FINANCIAL),
                    {
                        "org": self.org,
                        "store": sid,
                        "day": day,
                        "cur": currency,
                        "net": Decimal(net),
                        "orders": orders,
                        "cogs": None if cogs is None else Decimal(cogs),
                        "uncosted": 1 if cogs is None else 0,
                        "other": other[0] if other else 0,
                    },
                )
        return sid

    def ad_account(self, provider: str, currency: str, spend: dict, store=None) -> str:
        aid = str(uuid.uuid4())
        with self.db.begin() as db:
            db.execute(
                text(
                    "INSERT INTO ad_accounts (id, organization_id, external_resource_id, provider, "
                    "external_account_id, name, currency, timezone, platform_status, status, "
                    "history_from, first_import_completed_at, store_id) VALUES (:id, :org, :res, "
                    ":prov, :ext, :prov, :cur, 'Australia/Sydney', 'active', 'active', "
                    "'2025-09-14', :now, :store)"
                ),
                {
                    "id": aid,
                    "ext": aid,
                    "org": self.org,
                    "res": self._resource(db, "ad_account"),
                    "prov": provider,
                    "cur": currency,
                    "now": NOW,
                    "store": store,
                },
            )
            for day, cost in spend.items():
                db.execute(
                    text(
                        "INSERT INTO ad_performance_daily (id, organization_id, ad_account_id, "
                        "level, entity_key, day, impressions, clicks, cost, conversions, "
                        "conversion_value, currency, fetched_at) VALUES (gen_random_uuid(), :org, "
                        ":acc, 'account', 'account', :day, 0, 0, :cost, 0, 0, :cur, now())"
                    ),
                    {
                        "org": self.org,
                        "acc": aid,
                        "day": day,
                        "cost": Decimal(cost),
                        "cur": currency,
                    },
                )
        return aid

    def analytics_property(self, sessions: dict, store=None, currency="AUD") -> str:
        pid = str(uuid.uuid4())
        with self.db.begin() as db:
            db.execute(
                text(
                    "INSERT INTO analytics_properties (id, organization_id, external_resource_id, "
                    "provider, external_property_id, name, currency, timezone, platform_status, "
                    "status, history_from, first_import_completed_at, store_id) VALUES (:id, :org, "
                    ":res, 'fake', :ext, 'Site', :cur, 'Australia/Sydney', 'active', 'active', "
                    "'2025-09-14', :now, :store)"
                ),
                {
                    "id": pid,
                    "ext": pid,
                    "org": self.org,
                    "res": self._resource(db, "analytics_property"),
                    "cur": currency,
                    "now": NOW,
                    "store": store,
                },
            )
            for day, count in sessions.items():
                db.execute(
                    text(
                        "INSERT INTO analytics_daily (id, organization_id, property_id, day, "
                        "breakdown, dimension_key, sessions, engaged_sessions, total_users, "
                        "new_users, key_events, purchases, purchase_revenue, currency, fetched_at) "
                        "VALUES (gen_random_uuid(), :org, :prop, :day, 'total', 'total', :n, 0, 0, "
                        "0, 0, 1, 10, :cur, now())"
                    ),
                    {"org": self.org, "prop": pid, "day": day, "n": count, "cur": currency},
                )
        return pid


@pytest.fixture
def org(make_client, admin_engine):
    c = make_client()
    c.signup(f"metrics-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    c.seed = Seed(admin_engine, c.org, connected(c, c.org))
    return c


@pytest.fixture
def golden(org):
    s = org.seed
    org.store_id = s.store(days={D5: ("1000.00", 10, "400.00"), D6: ("500.50", 5, "200.20")})
    s.ad_account("google_ads", "AUD", {D5: "100.00", D6: "50.00", D7: "0"})
    s.ad_account("meta_ads", "USD", {D5: "20.00", D6: "10.00", D7: "5.00"})
    s.analytics_property({D5: 300, D6: 200, D7: 100})
    return org


def _metrics(runtime, c, first=D5, last=D7, store_id=None, currency="AUD", fx=FX):
    with runtime.db.transaction(org_id=uuid.UUID(c.org)) as session:
        scope = load_scope(
            session,
            organization_id=uuid.UUID(c.org),
            currency=currency,
            timezone="Australia/Sydney",
            now=NOW,
            store_id=uuid.UUID(store_id) if store_id else None,
        )
        inputs = load_inputs(session, scope, first, last, fx)
    return scope, inputs, compute(scope, inputs.period())


# ------------------------------------------------------------------ the golden period
def test_golden_values_to_the_cent(runtime, golden):
    _, _, m = _metrics(runtime, golden)
    assert m["net_sales"] == Figure(Decimal("1500.50"))
    assert m["orders"] == Figure(Decimal(15))
    assert m["product_cost"] == Figure(Decimal("600.20"))
    assert m["gross_profit"] == Figure(Decimal("900.30"))
    assert m["ad_spend"] == Figure(Decimal("204.50"))  # 150.00 AUD + 35.00 USD at 1.6 / 1.5
    assert m["profit_after_ad_spend"] == Figure(Decimal("695.80"))
    assert m["blended_roas"] == Figure(_q(Decimal("1500.50") / Decimal("204.50")))
    assert m["cost_per_order"] == Figure(_q(Decimal("204.50") / 15))
    assert m["ad_spend_share"] == Figure(_q(Decimal("204.50") / Decimal("1500.50")))
    assert m["gross_margin"] == Figure(_q(Decimal("900.30") / Decimal("1500.50")))
    assert m["sessions"] == Figure(Decimal(600))
    assert m["store_conversion_rate"] == Figure(Decimal("0.025000"))
    assert m["analytics_purchases"] == Figure(Decimal(3))
    assert m["analytics_revenue"] == Figure(Decimal(30))  # never added to net sales


def test_each_day_has_its_own_figures_and_rate(runtime, golden):
    _, inputs, _ = _metrics(runtime, golden)
    by_day = {d: compute(inputs.scope, inputs.period(d, d)) for d in (D5, D6, D7)}
    assert [by_day[d]["ad_spend"].value for d in (D5, D6, D7)] == [
        Decimal("132.00"),  # 100 + 20 x 1.6
        Decimal("65.00"),  # 50 + 10 x 1.5
        Decimal("7.50"),  # the 6th's rate on the 7th
    ]
    quiet = by_day[D7]
    assert (quiet["net_sales"], quiet["orders"]) == (Figure(Decimal(0)), Figure(Decimal(0)))
    assert quiet["blended_roas"] == Figure(Decimal("0.000000"))
    assert by_day[D7]["cost_per_order"] == Figure(None, "unavailable", "no_orders")


def test_figures_no_platform_provides_say_so(runtime, golden):
    _, _, m = _metrics(runtime, golden)
    assert m["shipping_cost"] == Figure(None, "unsupported", "not_provided_by_platform")
    assert m["payment_fees"] == Figure(None, "unsupported", "not_provided_by_platform")
    assert m["contribution_profit"] == Figure(None, "unsupported", "costs_not_entered")
    assert m["customer_acquisition_cost"] == Figure(
        None, "unavailable", "customer_key_not_collected"
    )


def test_converting_to_another_reporting_currency(runtime, golden):
    _, _, m = _metrics(runtime, golden, first=D5, last=D5, currency="USD")
    assert m["net_sales"] == Figure(Decimal("625.000"))  # 1,000 AUD / 1.6
    assert m["ad_spend"] == Figure(Decimal("82.500"))  # 100 / 1.6 + 20
    assert m["blended_roas"].value == _q(Decimal(1000) / Decimal(132))


# ------------------------------------------------------------------ never 0 for missing data
def test_a_day_not_read_makes_the_period_not_synchronized(runtime, golden):
    _, _, m = _metrics(runtime, golden, first=date(2025, 9, 12), last=D5)
    for key in ("net_sales", "ad_spend", "gross_profit", "blended_roas", "sessions"):
        assert m[key] == Figure(None, "not_synchronized", "not_synchronized"), key


def test_an_uncosted_product_makes_profit_unavailable_not_partial(runtime, org):
    org.seed.store(days={D5: ("100.00", 1, "40.00"), D6: ("50.00", 1, None)})
    _, _, m = _metrics(runtime, org)
    assert m["net_sales"] == Figure(Decimal("150.00"))
    for key in ("product_cost", "gross_profit", "gross_margin", "profit_after_ad_spend"):
        assert m[key].reason == "missing_product_costs", key
        assert m[key].value is None


def test_orders_in_another_currency_are_never_summed(runtime, org):
    org.seed.store(days={D5: ("100.00", 1, "40.00", 1)})
    _, _, m = _metrics(runtime, org, first=D5, last=D5)
    assert m["net_sales"] == Figure(None, "unavailable", "other_currency_orders")


def test_no_exchange_rate_is_not_available(runtime, org):
    org.seed.ad_account("meta_ads", "CHF", {D5: "10.00"})
    org.seed.store(days={D5: ("100.00", 1, "40.00")})
    _, _, m = _metrics(runtime, org, first=D5, last=D5)
    assert m["ad_spend"] == Figure(None, "unavailable", "no_exchange_rate")
    assert m["blended_roas"].reason == "no_exchange_rate"
    assert m["net_sales"].ok  # the store's own figures are unaffected


def test_nothing_connected_of_a_kind_says_so(runtime, org):
    org.seed.store(days={D5: ("100.00", 1, "40.00")})
    _, _, m = _metrics(runtime, org, first=D5, last=D5)
    assert m["ad_spend"] == Figure(None, "unavailable", "no_ad_account")
    assert m["profit_after_ad_spend"].reason == "no_ad_account"
    assert m["sessions"] == Figure(None, "unavailable", "no_analytics_property")
    assert m["gross_profit"] == Figure(Decimal("60.00"))


def test_a_store_still_importing_is_not_synchronized(runtime, org):
    org.seed.store(imported=False)
    _, _, m = _metrics(runtime, org, first=D5, last=D5)
    assert m["net_sales"].availability == "not_synchronized"


# ------------------------------------------------------------------ scope (Q-6-1)
def test_with_one_store_everything_counts_for_it(runtime, golden):
    scope, _, m = _metrics(runtime, golden, store_id=golden.store_id)
    assert (len(scope.ad_accounts), len(scope.properties)) == (2, 1)
    assert m["ad_spend"] == Figure(Decimal("204.50"))


def test_with_several_stores_only_assigned_sources_count(runtime, golden):
    s = golden.seed
    second = s.store(days={D5: ("80.00", 2, "30.00")})
    nz_ads = s.ad_account("google_ads", "AUD", {D5: "8.00"}, store=second)
    s.analytics_property({D5: 40}, store=second)
    scope, _, m = _metrics(runtime, golden, first=D5, last=D5, store_id=second)
    assert [a.id for a in scope.ad_accounts] == [uuid.UUID(nz_ads)]
    assert m["ad_spend"] == Figure(Decimal("8.00"))
    assert m["store_conversion_rate"] == Figure(Decimal("0.050000"))  # 2 orders / 40 sessions
    first_store = _metrics(runtime, golden, first=D5, last=D5, store_id=golden.store_id)[2]
    assert first_store["ad_spend"] == Figure(None, "unavailable", "no_ad_account")  # unassigned
    whole = _metrics(runtime, golden, first=D5, last=D5)[2]
    assert whole["ad_spend"] == Figure(Decimal("140.00"))  # 132.00 + 8.00
    assert whole["store_conversion_rate"].reason == "not_every_store_measured"


def test_another_organizations_figures_are_never_included(
    runtime, golden, make_client, admin_engine
):
    other = make_client()
    other.signup(f"other-{uuid.uuid4().hex[:6]}@example.com")
    other.org = other.create_org("Other")["id"]
    other.seed = Seed(admin_engine, other.org, connected(other, other.org))
    other.seed.store(days={D5: ("999.00", 9, "1.00")})
    _, _, m = _metrics(runtime, golden, first=D5, last=D5)
    assert m["net_sales"] == Figure(Decimal("1000.00"))


# ------------------------------------------------------------------ the registry
def test_every_metric_is_defined_once_with_its_formula():
    assert DEFINITION_VERSION == "analytics-v1"
    keys = [m.key for m in METRICS]
    assert len(keys) == len(set(keys)) == len(BY_KEY)
    for metric in METRICS:
        assert metric.formula and metric.label and metric.sources, metric.key
    assert "Before shipping costs and payment fees" in (BY_KEY["profit_after_ad_spend"].note or "")


def test_compute_answers_every_registry_metric(runtime, golden):
    _, _, m = _metrics(runtime, golden)
    assert set(m) == set(BY_KEY)
