"""WooCommerce in the store figures (task 2B-07, PHASE_02B_PLAN §6.7, Q-2B-2, Q-2B-5).

* **Parity:** the same sales give the same daily figures, to the cent, whether the store runs
  on Shopify or on WooCommerce (the two simulators hold the same sample store).
* **Status rule:** orders that are pending, failed, cancelled, drafts or in the trash are kept
  but never counted; an order that later becomes counted is added, and one that is cancelled
  is taken out again.
* **Currency rule:** orders in another currency are never summed; their days (placed or
  refunded) show "Not available — orders in other currencies", never a partial figure or 0.
"""

from __future__ import annotations

import copy
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.commerce.importer import SyncMode, enqueue_reconciliations
from sqlalchemy import text

from tests.shopify_sim import ShopifySim, callback_params, sample_catalogue, sample_orders
from tests.shopify_sim import build_provider as build_shopify
from tests.woocommerce_sim import WooSim, approve, build_provider, sample_store

HOST = "shop.example.com"
SHOP = "eve-zone.myshopify.com"
PERIOD = "from=2026-10-01&to=2026-10-12"
MONEY = (
    "gross_sales",
    "discounts",
    "sales_reversals",
    "net_sales",
    "shipping",
    "taxes",
    "duties",
    "fees",
    "total_sales",
)


@pytest.fixture
def sim(runtime, settings):
    s = WooSim()
    sample_store(s.add_store(HOST))
    runtime.providers.register(
        build_provider(s, reconcile_interval=settings.WOOCOMMERCE_RECONCILE_INTERVAL)
    )
    return s


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def _client(make_client, name):
    c = make_client()
    c.email = f"{name}-{uuid.uuid4().hex[:6]}@example.com"
    c.signup(c.email)
    c.org = c.create_org(f"{name} Co")["id"]
    return c


def _link_woo(make_client, sim):
    c = _client(make_client, "woo")
    started = c.post(
        f"/organizations/{c.org}/connections/woocommerce/start", {"params": {"store_url": HOST}}
    ).json()["data"]["authorize_url"]
    _, returned = approve(make_client().http, c.http, sim, started)
    return _finish_link(c, returned)


def _link_shopify(make_client, runtime, clock):
    shopify = ShopifySim()
    shopify.add_shop(SHOP, catalogue=sample_catalogue(), orders=sample_orders())
    runtime.providers.register(build_shopify(shopify, clock))
    c = _client(make_client, "shopify")
    started = c.post(
        f"/organizations/{c.org}/connections/shopify/start", {"params": {"shop_domain": SHOP}}
    ).json()["data"]["authorize_url"]
    returned = c.http.get(
        "/api/v1/connections/shopify/callback",
        params=callback_params(started),
        follow_redirects=False,
    )
    return _finish_link(c, returned)


def _finish_link(c, returned):
    c.conn = parse_qs(urlsplit(returned.headers["location"]).query)["connection_id"][0]
    (resource,) = c.get(f"/organizations/{c.org}/connections/{c.conn}/resources").json()["data"]
    assert c.post(f"/organizations/{c.org}/resources/{resource['id']}/link").status_code == 201
    (c.store,) = c.get(f"/organizations/{c.org}/stores").json()["data"]
    return c


def _metrics(c, period=PERIOD):
    response = c.get(f"/organizations/{c.org}/stores/{c.store['id']}/metrics/daily?{period}")
    if response.status_code == 401:  # a simulated day passed: the session ended
        c.login(c.email)
        c.refresh_csrf()
        response = c.get(f"/organizations/{c.org}/stores/{c.store['id']}/metrics/daily?{period}")
    assert response.status_code == 200
    return response.json()["data"]


def _days(c, period=PERIOD):
    return {d["day"]: d for d in _metrics(c, period)["days"]}


def _extra_order(store, order_id, **changes):
    """A copy of the sample order (same lines, own ids) with ``changes``, without refunds."""
    order = copy.deepcopy(store.orders[0])
    order.update(id=order_id, number=str(order_id), refunds=[], **changes)
    for offset, line in enumerate([*order["line_items"], *order["shipping_lines"]]):
        line["id"] = order_id * 10 + offset
    store.orders.append(order)
    return order


# ------------------------------------------------------------------ parity
def _figures(day):
    return {
        "availability": day["availability"],
        "orders_count": day["orders_count"],
        **{name: day[name] for name in MONEY},
        "cogs": day["cogs"],
        "gross_profit": day["gross_profit"],
        "cost_coverage": day["cost_coverage"],
    }


def test_the_same_sales_give_identical_figures_on_shopify_and_woocommerce(
    make_client, runtime, sim, clock, admin_engine
):
    shopify = _link_shopify(make_client, runtime, clock)
    woo = _link_woo(make_client, sim)
    assert (shopify.store["currency"], shopify.store["timezone"]) == (
        woo.store["currency"],
        woo.store["timezone"],
    )

    a, b = _metrics(shopify), _metrics(woo)
    assert [_figures(d) for d in a["days"]] == [_figures(d) for d in b["days"]]
    assert a["totals"] == b["totals"]
    assert a["totals"]["availability"] == "available"

    # The stored components are equal too (the reusable base for later phases).
    stored = _rows(
        admin_engine,
        "SELECT s.provider, f.day, f.gross_sales, f.discounts, f.sales_reversals, f.net_sales,"
        " f.shipping, f.taxes, f.duties, f.fees, f.total_sales, f.orders_count, f.cogs,"
        " f.costed_net_sales, f.uncosted_lines, f.other_currency_orders"
        " FROM financial_daily f JOIN stores s ON s.id = f.store_id ORDER BY f.day, s.provider",
    )
    by_provider = {"shopify": [], "woocommerce": []}
    for row in stored:
        by_provider[row.pop("provider")].append(row)
    assert by_provider["shopify"] == by_provider["woocommerce"]
    assert [r["day"].isoformat() for r in by_provider["woocommerce"]] == [
        "2026-10-05",
        "2026-10-08",
    ]


def test_parity_golden_values(make_client, sim):
    """The 2A-08 golden values, reached through WooCommerce."""
    days = _days(_link_woo(make_client, sim))
    sale, refund = days["2026-10-05"], days["2026-10-08"]
    assert (sale["gross_sales"], sale["discounts"], sale["net_sales"]) == (
        "50.810000",
        "2.000000",
        "48.810000",
    )
    assert (sale["shipping"], sale["taxes"], sale["total_sales"]) == (
        "9.080000",
        "5.800000",
        "63.690000",
    )
    assert sale["orders_count"] == 1
    assert sale["cogs"] == {
        "value": None,
        "availability": "unavailable",
        "reason": "missing_product_costs",
    }
    assert (refund["sales_reversals"], refund["total_sales"]) == ("18.900000", "-20.790000")
    assert refund["orders_count"] == 0
    assert days["2026-10-06"]["total_sales"] == "0"  # synced, no activity: a real 0


# ------------------------------------------------------------------ status rule (Q-2B-2)
@pytest.mark.parametrize("status", ["pending", "failed", "cancelled", "checkout-draft"])
def test_orders_that_do_not_count_are_left_out_of_the_figures(
    make_client, sim, admin_engine, status
):
    _extra_order(sim.stores[HOST], 510, status=status)
    owner = _link_woo(make_client, sim)
    assert _rows(admin_engine, "SELECT count(*) AS n FROM orders") == [{"n": 2}]  # kept
    sale = _days(owner)["2026-10-05"]
    assert (sale["orders_count"], sale["total_sales"]) == (1, "63.690000")  # only order 500


def test_an_order_is_counted_once_paid_and_taken_out_when_cancelled(
    make_client, runtime, sim, clock
):
    store = sim.stores[HOST]
    order = _extra_order(store, 511, status="pending", date_modified_gmt="2026-10-05T02:00:00")
    owner = _link_woo(make_client, sim)
    assert _days(owner)["2026-10-05"]["orders_count"] == 1

    order.update(status="processing", date_modified_gmt="2026-10-14T00:10:00")
    clock.advance(timedelta(minutes=16))
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1
    sale = _days(owner)["2026-10-05"]
    assert (sale["orders_count"], sale["total_sales"]) == (2, "127.380000")

    order.update(status="cancelled", date_modified_gmt="2026-10-14T00:30:00")
    clock.advance(timedelta(minutes=16))
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1
    sale = _days(owner)["2026-10-05"]
    assert (sale["orders_count"], sale["total_sales"]) == (1, "63.690000")


def test_on_hold_orders_count_by_default(make_client, sim):
    """Only pending, failed, cancelled, drafts and trash are left out (Q-2B-2)."""
    _extra_order(sim.stores[HOST], 512, status="on-hold")
    owner = _link_woo(make_client, sim)
    assert _days(owner)["2026-10-05"]["orders_count"] == 2


# ------------------------------------------------------------------ currency rule (Q-2B-5)
def test_a_day_with_an_order_in_another_currency_is_not_available(make_client, sim, admin_engine):
    _extra_order(sim.stores[HOST], 520, currency="USD", date_created_gmt="2026-10-06T02:00:00")
    owner = _link_woo(make_client, sim)
    data = _metrics(owner)
    days = {d["day"]: d for d in data["days"]}

    other = days["2026-10-06"]
    assert (other["availability"], other["reason"]) == ("unavailable", "other_currency_orders")
    assert all(other[name] is None for name in (*MONEY, "orders_count"))  # never 0, never partial
    assert other["cogs"] == {
        "value": None,
        "availability": "unavailable",
        "reason": "other_currency_orders",
    }
    # Other days are untouched.
    assert days["2026-10-05"]["total_sales"] == "63.690000"
    assert (days["2026-10-07"]["availability"], days["2026-10-07"]["total_sales"]) == (
        "available",
        "0",
    )
    # A period total would mix currencies or understate: none is given.
    totals = data["totals"]
    assert (totals["availability"], totals["reason"]) == ("unavailable", "other_currency_orders")
    assert totals["total_sales"] is None and totals["gross_margin"]["value"] is None
    # A period without that day is complete.
    clean = _metrics(owner, "from=2026-10-07&to=2026-10-12")["totals"]
    assert (clean["availability"], clean["reason"]) == ("available", None)

    (row,) = _rows(
        admin_engine,
        "SELECT total_sales, orders_count, other_currency_orders FROM financial_daily"
        " WHERE day = '2026-10-06'",
    )
    assert row == {"total_sales": Decimal(0), "orders_count": 0, "other_currency_orders": 1}


def test_the_refund_day_of_an_order_in_another_currency_is_not_available_either(make_client, sim):
    store = sim.stores[HOST]
    order = _extra_order(store, 521, currency="USD", date_created_gmt="2026-10-06T02:00:00")
    order["refunds"] = [{"id": 950, "reason": "", "total": "-20.79"}]
    refund = copy.deepcopy(store.refunds[0])
    refund.update(id=950, parent_id=521, date_created_gmt="2026-10-09T03:00:00")
    refunded = [{"key": "_refunded_item_id", "value": "5210"}]  # line 1 of order 521
    refund["line_items"][0].update(id=951, meta_data=refunded)
    store.refunds.append(refund)
    days = _days(_link_woo(make_client, sim))
    assert days["2026-10-09"]["reason"] == "other_currency_orders"
    assert days["2026-10-06"]["reason"] == "other_currency_orders"
    assert days["2026-10-08"]["total_sales"] == "-20.790000"  # the store-currency refund


def test_a_store_currency_refund_and_another_currency_sale_on_one_day(make_client, sim):
    _extra_order(sim.stores[HOST], 522, currency="EUR", date_created_gmt="2026-10-08T04:00:00")
    day = _days(_link_woo(make_client, sim))["2026-10-08"]
    assert (day["availability"], day["total_sales"]) == ("unavailable", None)


def test_unsynced_days_take_precedence_over_other_currency_days(make_client, sim):
    _extra_order(sim.stores[HOST], 523, currency="USD", date_created_gmt="2026-10-06T02:00:00")
    owner = _link_woo(make_client, sim)
    totals = _metrics(owner, "from=2026-10-06&to=2026-10-20")["totals"]  # runs past today
    assert (totals["availability"], totals["reason"]) == ("not_synchronized", "not_synchronized")
