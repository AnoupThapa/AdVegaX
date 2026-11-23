"""Campaigns and products in the unified API (task 6-06, Q-6-9, Q-6-10, Q-6-11).

Campaigns: each campaign's platform-reported figures (converted with each day's rate), budget
use against today's daily budget, and Google Analytics' figures for the campaign of exactly the
same name. Products: units, net sales, product cost, gross profit and margin per product, from
the stores' sales records with finance-v1's rules; never ad spend per product.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.api.test_metrics_engine import D5, D6, D7, Seed
from tests.api.test_unified_analytics_api import rates  # noqa: F401  (fixture)
from tests.helpers import connected

PERIOD = "?from=2026-10-05&to=2026-10-07"


def _exec(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        db.execute(text(sql), params)


def _campaign(admin_engine, org, account, name, *, budget=None, days=()):
    """A campaign with an optional budget (period, amount, shared) and campaign-level days."""
    cid, bid = str(uuid.uuid4()), None
    if budget is not None:
        bid = str(uuid.uuid4())
        period, amount, shared = budget
        _exec(
            admin_engine,
            "INSERT INTO ad_budgets (id, organization_id, ad_account_id, external_budget_id, "
            "level, period, amount, currency, shared) SELECT :id, :org, :acc, :ext, 'campaign', "
            ":period, :amount, currency, :shared FROM ad_accounts WHERE id = :acc",
            id=bid,
            ext=bid,
            org=org,
            acc=account,
            period=period,
            amount=amount,
            shared=shared,
        )
    _exec(
        admin_engine,
        "INSERT INTO ad_campaigns (id, organization_id, ad_account_id, external_campaign_id, "
        "name, status, budget_id) VALUES (:id, :org, :acc, :ext, :name, 'active', :budget)",
        id=cid,
        ext=cid,
        org=org,
        acc=account,
        name=name,
        budget=bid,
    )
    for day, cost, clicks, conversions, value in days:
        _exec(
            admin_engine,
            "INSERT INTO ad_performance_daily (id, organization_id, ad_account_id, level, "
            "entity_key, campaign_id, day, impressions, clicks, cost, conversions, "
            "conversion_value, currency, fetched_at) SELECT gen_random_uuid(), :org, :acc, "
            "'campaign', :key, :cid, :day, 100, :clicks, :cost, :conv, :value, currency, now() "
            "FROM ad_accounts WHERE id = :acc",
            org=org,
            acc=account,
            cid=cid,
            key=cid,
            day=day,
            cost=Decimal(cost),
            clicks=clicks,
            conv=Decimal(conversions),
            value=Decimal(value),
        )
    return cid


def _ga_source(admin_engine, org, prop, day, source, medium, campaign, sessions, revenue):
    _exec(
        admin_engine,
        "INSERT INTO analytics_daily (id, organization_id, property_id, day, breakdown, "
        "dimension_key, traffic_source, traffic_medium, campaign, sessions, engaged_sessions, "
        "total_users, new_users, key_events, purchases, purchase_revenue, currency, fetched_at) "
        "VALUES (gen_random_uuid(), :org, :prop, :day, 'source', :key, :src, :med, :camp, :n, 0, "
        "0, 0, 0, 1, :rev, 'AUD', now())",
        org=org,
        prop=prop,
        day=day,
        key=f"{source}|{medium}|{campaign}",
        src=source,
        med=medium,
        camp=campaign,
        n=sessions,
        rev=Decimal(revenue),
    )


@pytest.fixture
def owner(make_client, admin_engine, rates):  # noqa: F811
    c = make_client()
    c.signup(f"camp-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    c.seed = Seed(admin_engine, c.org, connected(c, c.org))
    c.store_id = c.seed.store()
    c.google = c.seed.ad_account("google_ads", "AUD", {D5: "100", D6: "50", D7: "0"})
    c.meta = c.seed.ad_account("meta_ads", "USD", {D5: "20", D6: "10", D7: "5"})
    c.prop = c.seed.analytics_property({D5: 300, D6: 200, D7: 100})
    return c


def _get(c, path, query=PERIOD):
    response = c.get(f"/organizations/{c.org}/analytics/{path}{query}")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _v(fig):
    return None if fig["value"] is None else Decimal(fig["value"])


# ------------------------------------------------------------------ campaigns
def test_campaigns_with_their_figures_budget_use_and_google_analytics_match(owner, admin_engine):
    _campaign(
        admin_engine,
        owner.org,
        owner.google,
        "Spring Sale",
        budget=("daily", Decimal("60"), False),
        days=[(D5, "100", 10, "2", "300"), (D6, "50", 5, "1", "150")],
    )
    _campaign(
        admin_engine,
        owner.org,
        owner.meta,
        "Gloves - Sales",
        budget=("lifetime", Decimal("500"), False),
        days=[(D5, "20", 4, "1", "50")],
    )
    _ga_source(admin_engine, owner.org, owner.prop, D5, "google", "cpc", "Spring Sale", 40, "120.5")
    _ga_source(admin_engine, owner.org, owner.prop, D6, "google", "cpc", "Spring Sale", 10, "30")
    _ga_source(
        admin_engine, owner.org, owner.prop, D5, "facebook", "paid", "Gloves - Sales", 7, "0"
    )
    _ga_source(admin_engine, owner.org, owner.prop, D5, "google", "organic", "Spring Sale", 99, "9")
    data = _get(owner, "campaigns")
    items = {c["name"]: c for c in data["items"]}
    assert list(items) == ["Gloves - Sales", "Spring Sale"]  # by name
    keys = {d["key"] for d in data["definitions"]}
    assert keys == set(items["Spring Sale"]["figures"]) | set(items["Spring Sale"]["analytics"])
    spring = items["Spring Sale"]
    assert (spring["provider"], spring["source"], spring["budget_period"]) == (
        "google_ads",
        "platform_reported",
        "daily",
    )
    f = spring["figures"]
    assert (_v(f["spend"]), _v(f["clicks"]), _v(f["conversion_value"])) == (
        Decimal(150),
        Decimal(15),
        Decimal(450),
    )
    assert f["platform_roas"]["value"] == "3.000000"
    assert f["budget_use"]["value"] == "0.833333"  # 150 / (60 a day x 3 days)
    ga = spring["analytics"]
    assert (_v(ga["sessions"]), _v(ga["purchase_revenue"])) == (Decimal(50), Decimal("150.5"))
    gloves = items["Gloves - Sales"]
    assert _v(gloves["figures"]["spend"]) == Decimal("32.0")  # 20 USD x 1.6 on the 5th
    assert gloves["figures"]["budget_use"] == {
        "value": None,
        "availability": "unsupported",
        "reason": "not_a_daily_budget",
    }
    assert _v(gloves["analytics"]["sessions"]) == Decimal(7)


def test_campaigns_without_a_match_activity_or_budget_say_so(owner, admin_engine):
    _campaign(admin_engine, owner.org, owner.google, "Brand", days=[])
    _campaign(
        admin_engine,
        owner.org,
        owner.google,
        "Shared",
        budget=("daily", Decimal("10"), True),
        days=[(D5, "5", 1, "0", "0")],
    )
    items = {c["name"]: c for c in _get(owner, "campaigns")["items"]}
    brand = items["Brand"]
    assert _v(brand["figures"]["spend"]) == Decimal(0)  # read, no activity: a real zero
    assert brand["figures"]["platform_roas"]["reason"] == "no_ad_spend"
    assert brand["figures"]["budget_use"]["reason"] == "no_budget"
    assert brand["analytics"]["sessions"] == {
        "value": None,
        "availability": "unavailable",
        "reason": "no_match",
    }
    assert items["Shared"]["figures"]["budget_use"]["reason"] == "shared_budget"


def test_campaigns_for_a_period_not_read(owner, admin_engine):
    _campaign(admin_engine, owner.org, owner.google, "Old", days=[])
    (old,) = _get(owner, "campaigns", "?from=2025-09-01&to=2025-09-30")["items"]
    assert old["figures"]["spend"]["availability"] == "not_synchronized"
    assert old["analytics"] is None
    assert old["analytics_missing"]["availability"] == "not_synchronized"


def test_campaigns_without_a_property(make_client, admin_engine, rates):  # noqa: F811
    c = make_client()
    c.signup(f"np-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("No GA")["id"]
    seed = Seed(admin_engine, c.org, connected(c, c.org))
    account = seed.ad_account("google_ads", "AUD", {D5: "1"})
    _campaign(admin_engine, c.org, account, "Only", days=[(D5, "1", 1, "0", "0")])
    (only,) = _get(c, "campaigns", "?from=2026-10-05&to=2026-10-05")["items"]
    assert (only["analytics"], only["analytics_missing"]["reason"]) == (
        None,
        "no_analytics_property",
    )


# ------------------------------------------------------------------ products
def _product(admin_engine, org, store, title):
    pid, vid = str(uuid.uuid4()), str(uuid.uuid4())
    _exec(
        admin_engine,
        "INSERT INTO products (id, organization_id, store_id, external_product_id, title, status) "
        "VALUES (:id, :org, :store, :ext, :title, 'active')",
        id=pid,
        ext=pid,
        org=org,
        store=store,
        title=title,
    )
    _exec(
        admin_engine,
        "INSERT INTO product_variants (id, organization_id, store_id, product_id, "
        "external_variant_id) VALUES (:id, :org, :store, :product, :ext)",
        id=vid,
        ext=vid,
        org=org,
        store=store,
        product=pid,
    )
    return vid


def _sale(admin_engine, org, store, variant, when, action, qty, amount, cost, currency="AUD"):
    oid, iid = str(uuid.uuid4()), str(uuid.uuid4())
    _exec(
        admin_engine,
        "INSERT INTO orders (id, organization_id, store_id, external_order_id, currency, "
        "ordered_at, total_amount) VALUES (:id, :org, :store, :ext, :cur, :when, :amount)",
        id=oid,
        ext=oid,
        org=org,
        store=store,
        cur=currency,
        when=when,
        amount=abs(Decimal(amount)),
    )
    _exec(
        admin_engine,
        "INSERT INTO order_items (id, organization_id, order_id, variant_id, "
        "external_line_item_id, quantity, unit_cost, cost_source) VALUES (:id, :org, :order, "
        ":variant, :ext, "
        ":qty, :cost, CASE WHEN :has_cost THEN 'order_time' END)",
        id=iid,
        ext=iid,
        org=org,
        order=oid,
        variant=variant,
        qty=abs(qty),
        cost=None if cost is None else Decimal(cost),
        has_cost=cost is not None,
    )
    _exec(
        admin_engine,
        "INSERT INTO sales_entries (id, organization_id, store_id, order_id, order_item_id, "
        "external_agreement_id, external_sale_id, happened_at, action, line_type, quantity, "
        "amount, currency) VALUES (gen_random_uuid(), :org, :store, :order, :item, :ext, :ext, "
        ":when, :action, 'product', :qty, :amount, :cur)",
        org=org,
        store=store,
        order=oid,
        item=iid,
        ext=iid,
        when=when,
        action=action,
        qty=qty,
        amount=Decimal(amount),
        cur=currency,
    )


def test_products_with_units_sales_cost_and_margin(owner, admin_engine):
    gloves = _product(admin_engine, owner.org, owner.store_id, "Nitrile gloves")
    masks = _product(admin_engine, owner.org, owner.store_id, "Face masks")
    # 5 October 10:00 Sydney = 4 October 23:00 UTC
    _sale(
        admin_engine,
        owner.org,
        owner.store_id,
        gloves,
        "2026-10-04T23:00:00Z",
        "order",
        4,
        "100",
        "10",
    )
    _sale(
        admin_engine,
        owner.org,
        owner.store_id,
        gloves,
        "2026-10-06T01:00:00Z",
        "return",
        -1,
        "-25",
        "10",
    )
    _sale(
        admin_engine,
        owner.org,
        owner.store_id,
        masks,
        "2026-10-05T02:00:00Z",
        "order",
        2,
        "30",
        None,
    )
    _sale(
        admin_engine,
        owner.org,
        owner.store_id,
        masks,
        "2026-10-01T02:00:00Z",
        "order",
        9,
        "90",
        "1",
    )
    _sale(
        admin_engine,
        owner.org,
        owner.store_id,
        gloves,
        "2026-10-05T03:00:00Z",
        "order",
        1,
        "7",
        "1",
        "NZD",
    )
    data = _get(owner, "products")
    items = {p["title"]: p for p in data["items"]}
    assert [p["title"] for p in data["items"]] == ["Nitrile gloves", "Face masks"]
    g = items["Nitrile gloves"]["figures"]
    assert (_v(g["units"]), _v(g["net_sales"]), _v(g["product_cost"])) == (
        Decimal(3),
        Decimal(75),
        Decimal(30),
    )
    assert (_v(g["gross_profit"]), g["gross_margin"]["value"]) == (Decimal(45), "0.600000")
    m = items["Face masks"]["figures"]
    assert _v(m["net_sales"]) == Decimal(30)  # the 1 October sale is outside the period
    assert m["product_cost"]["reason"] == "missing_product_costs"
    assert m["gross_profit"]["reason"] == "missing_product_costs"
    assert data["other_currency_lines"] == 1  # never summed with AUD
    assert data["items_missing"] is None
    assert "ad_spend" not in g  # never ad spend per product (Q-6-10)
    assert {d["key"] for d in data["definitions"]} == set(g)  # "How is this calculated?"


def test_products_for_a_period_not_read_or_without_a_store(owner, make_client):
    data = _get(owner, "products", "?from=2025-09-01&to=2025-09-30")
    assert (data["items"], data["items_missing"]["availability"]) == ([], "not_synchronized")
    c = make_client()
    c.signup(f"ns-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("No store")["id"]
    assert _get(c, "products")["items_missing"]["reason"] == "no_store"


def test_outsiders_cannot_read_campaigns_or_products(owner, make_client):
    outsider = make_client()
    outsider.signup(f"x-{uuid.uuid4().hex[:6]}@example.com")
    for path in ("campaigns", "products"):
        assert outsider.get(f"/organizations/{owner.org}/analytics/{path}").status_code == 404
