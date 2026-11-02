"""Importing a WooCommerce store page by page (task 2B-05, PHASE_02B_PLAN §9-§10).

Connect → link → the paged import reads products, variations, orders and refunds from the
WooCommerce simulator's sample store (the same store as the Shopify sample) through the real
API, database and job runner. Customer details sent by the store are never stored.
"""

from __future__ import annotations

import copy
import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.commerce.importer import SyncMode, enqueue_reconciliations
from app.providers.woocommerce import provider as woo_provider
from sqlalchemy import text

from tests.woocommerce_sim import CUSTOMER, WooSim, approve, build_provider, sample_store

HOST = "shop.example.com"


@pytest.fixture
def sim(runtime):
    s = WooSim()
    sample_store(s.add_store(HOST))
    runtime.providers.register(build_provider(s))
    return s


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def _link(make_client, sim):
    c = make_client()
    c.signup("woo-import@example.com")
    c.org = c.create_org("Import Co")["id"]
    started = c.post(
        f"/organizations/{c.org}/connections/woocommerce/start",
        {"params": {"store_url": HOST}},
    ).json()["data"]["authorize_url"]
    _, returned = approve(make_client().http, c.http, sim, started)
    query = parse_qs(urlsplit(returned.headers["location"]).query)
    c.conn = query["connection_id"][0]
    (resource,) = c.get(f"/organizations/{c.org}/connections/{c.conn}/resources").json()["data"]
    assert c.post(f"/organizations/{c.org}/resources/{resource['id']}/link").status_code == 201
    (c.store,) = c.get(f"/organizations/{c.org}/stores").json()["data"]
    return c


def test_the_store_is_imported_with_its_catalogue_orders_and_refunds(
    make_client, sim, clock, admin_engine
):
    owner = _link(make_client, sim)
    store = owner.store
    assert (store["status"], store["currency"], store["timezone"]) == (
        "active",
        "AUD",
        "Australia/Sydney",
    )
    assert store["first_import_completed_at"] is not None
    (row,) = _rows(admin_engine, "SELECT history_from FROM stores")
    assert clock.now() - row["history_from"] == timedelta(days=395)  # 13 months (Q-2B-4)

    products = _rows(
        admin_engine,
        "SELECT external_product_id, title, status, product_type FROM products ORDER BY 1",
    )
    assert products == [
        {
            "external_product_id": "10",
            "title": "Nitrile Gloves",
            "status": "active",
            "product_type": "Gloves",
        },
        {
            "external_product_id": "20",
            "title": "Gift Wrap",
            "status": "unlisted",
            "product_type": None,
        },
    ]
    variants = _rows(
        admin_engine,
        "SELECT v.external_variant_id, v.title, v.sku, v.price, v.inventory_tracked, "
        "v.inventory_available, h.unit_cost FROM product_variants v "
        "LEFT JOIN product_cost_history h ON h.variant_id = v.id ORDER BY 1",
    )
    assert variants == [
        {
            "external_variant_id": "11",
            "title": "Medium",
            "sku": "NG-M",
            "price": Decimal("19.9"),
            "inventory_tracked": True,
            "inventory_available": 120,
            "unit_cost": Decimal("7.25"),
        },
        {
            "external_variant_id": "12",
            "title": "Large",
            "sku": "NG-L",
            "price": Decimal("21.9"),
            "inventory_tracked": True,
            "inventory_available": 0,
            "unit_cost": None,
        },
        {
            "external_variant_id": "20",
            "title": None,
            "sku": None,
            "price": Decimal("5"),
            "inventory_tracked": False,
            "inventory_available": None,
            "unit_cost": Decimal("1.1"),
        },
    ]

    (order,) = _rows(
        admin_engine,
        "SELECT external_order_id, order_number, financial_status, tax_amount, refund_amount, "
        "total_amount, gross_amount, excluded_reason, customer_key FROM orders",
    )
    assert order == {
        "external_order_id": "500",
        "order_number": "1001",
        "financial_status": "completed",
        "tax_amount": Decimal("5.8"),
        "refund_amount": Decimal("20.79"),
        "total_amount": Decimal("63.69"),
        "gross_amount": order["gross_amount"],
        "excluded_reason": None,
        "customer_key": None,
    }
    lines = _rows(
        admin_engine,
        "SELECT external_line_item_id, quantity, unit_cost, cost_source, "
        "variant_id IS NOT NULL AS linked FROM order_items ORDER BY 1",
    )
    assert lines == [
        {
            "external_line_item_id": "601",
            "quantity": 2,
            "unit_cost": Decimal("7.25"),
            "cost_source": "order_time",
            "linked": True,
        },
        {
            "external_line_item_id": "602",
            "quantity": 1,
            "unit_cost": None,
            "cost_source": None,
            "linked": False,
        },
    ]
    sales = _rows(
        admin_engine,
        "SELECT external_sale_id, action, line_type, amount, discount_amount, tax_amount, "
        "quantity, order_item_id IS NOT NULL AS linked FROM sales_entries ORDER BY 1",
    )
    assert sales == [
        {
            "external_sale_id": "line:601",
            "action": "order",
            "line_type": "product",
            "amount": Decimal("41.58"),
            "discount_amount": Decimal("2"),
            "tax_amount": Decimal("3.78"),
            "quantity": 2,
            "linked": True,
        },
        {
            "external_sale_id": "line:602",
            "action": "order",
            "line_type": "product",
            "amount": Decimal("12.11"),
            "discount_amount": Decimal("0"),
            "tax_amount": Decimal("1.1"),
            "quantity": 1,
            "linked": True,
        },
        {
            "external_sale_id": "refund-line:900:901",
            "action": "return",
            "line_type": "product",
            "amount": Decimal("-20.79"),
            "discount_amount": Decimal("-1"),
            "tax_amount": Decimal("-1.89"),
            "quantity": -1,
            "linked": True,
        },
        {
            "external_sale_id": "shipping:603",
            "action": "order",
            "line_type": "shipping",
            "amount": Decimal("10"),
            "discount_amount": Decimal("0"),
            "tax_amount": Decimal("0.92"),
            "quantity": None,
            "linked": False,
        },
    ]
    refunds = _rows(admin_engine, "SELECT external_refund_id, total_amount FROM refunds")
    assert refunds == [{"external_refund_id": "900", "total_amount": Decimal("20.79")}]
    # The daily figures are those of the identical Shopify store (2A-08 golden values).
    data = owner.get(
        f"/organizations/{owner.org}/stores/{store['id']}/metrics/daily?from=2026-10-05&to=2026-10-08"
    ).json()["data"]
    days = {d["day"]: d for d in data["days"]}
    assert (days["2026-10-05"]["net_sales"], days["2026-10-05"]["total_sales"]) == (
        "48.810000",
        "63.690000",
    )
    assert days["2026-10-05"]["cogs"]["availability"] == "unavailable"  # the engraving line


def test_customer_details_are_neither_requested_nor_stored(make_client, sim, admin_engine, caplog):
    caplog.set_level(logging.DEBUG)
    _link(make_client, sim)
    order_calls = sim.calls("/wc/v3/orders")
    assert order_calls and all("_fields" in c.url.params for c in order_calls)
    assert "billing" not in order_calls[0].url.params["_fields"]
    dumped = ""
    for table in (
        "orders",
        "order_items",
        "sales_entries",
        "refunds",
        "products",
        "product_variants",
        "audit_logs",
        "external_resources",
    ):
        dumped += json.dumps(_rows(admin_engine, f"SELECT * FROM {table}"), default=str)
    for secret in (*CUSTOMER.values(), "Leave at the back door"):
        assert secret not in dumped
        assert secret not in caplog.text


def test_a_store_that_ignores_the_field_list_still_leaks_nothing(
    make_client, sim, admin_engine, monkeypatch
):
    monkeypatch.setattr(woo_provider.mapping, "ORDER_FIELDS", "")  # nothing restricted
    _link(make_client, sim)
    dumped = json.dumps(_rows(admin_engine, "SELECT * FROM orders"), default=str)
    assert CUSTOMER["email"] not in dumped and CUSTOMER["last_name"] not in dumped


def test_many_small_pages_give_the_same_store(make_client, sim, admin_engine, monkeypatch):
    monkeypatch.setattr(woo_provider, "PER_PAGE", 1)
    monkeypatch.setattr(woo_provider, "VARIABLE_PER_PAGE", 1)
    store = sim.stores[HOST]
    store.variations[10].append({**copy.deepcopy(store.variations[10][0]), "id": 13, "sku": "NG-S"})
    store.products.append({**copy.deepcopy(store.products[0]), "id": 30, "name": "Masks"})
    store.variations[30] = [{**copy.deepcopy(store.variations[10][1]), "id": 31, "sku": "MK-1"}]
    _link(make_client, sim)
    assert len(sim.calls("/wc/v3/products/10/variations")) == 3  # one variation per page
    variants = _rows(admin_engine, "SELECT external_variant_id FROM product_variants ORDER BY 1")
    assert [v["external_variant_id"] for v in variants] == ["11", "12", "13", "20", "31"]
    assert len(_rows(admin_engine, "SELECT id FROM sales_entries")) == 4
    (state,) = _rows(admin_engine, "SELECT import_cursor, import_progress FROM commerce_sync_state")
    assert (state["import_cursor"], state["import_progress"]) == (None, 100)


def test_orders_are_read_from_the_history_window_with_gmt_dates(make_client, sim, clock):
    _link(make_client, sim)
    params = sim.calls("/wc/v3/orders")[0].url.params
    assert params["dates_are_gmt"] == "true"
    assert params["after"] == (clock.now() - timedelta(days=395)).strftime("%Y-%m-%dT%H:%M:%S")
    assert "modified_after" not in params
    refunds = sim.calls("/wc/v3/refunds")[0].url.params
    assert refunds["after"] == params["after"]
    assert "after" not in sim.calls("/wc/v3/products")[0].url.params


def test_uncounted_orders_are_kept_with_the_reason(make_client, sim, admin_engine):
    store = sim.stores[HOST]
    base = store.orders[0]
    store.orders += [
        {
            **copy.deepcopy(base),
            "id": 501,
            "status": "pending",
            "line_items": [],
            "shipping_lines": [],
            "refunds": [],
        },
        {
            **copy.deepcopy(base),
            "id": 502,
            "status": "processing",
            "currency": "USD",
            "line_items": [],
            "shipping_lines": [],
            "refunds": [],
        },
        {
            **copy.deepcopy(base),
            "id": 503,
            "status": "on-hold",
            "line_items": [],
            "shipping_lines": [],
            "refunds": [],
        },
    ]
    _link(make_client, sim)
    rows = _rows(admin_engine, "SELECT external_order_id, excluded_reason FROM orders ORDER BY 1")
    assert rows == [
        {"external_order_id": "500", "excluded_reason": None},
        {"external_order_id": "501", "excluded_reason": "status"},
        {"external_order_id": "502", "excluded_reason": "other_currency"},
        {"external_order_id": "503", "excluded_reason": None},
    ]


def test_without_cogs_lines_have_no_cost_even_if_the_product_has_one(
    make_client, sim, admin_engine
):
    store = sim.stores[HOST]
    del store.orders[0]["line_items"][0]["cost_of_goods_sold"]  # sold before COGS was on
    _link(make_client, sim)
    (line,) = _rows(
        admin_engine,
        "SELECT unit_cost, cost_source FROM order_items WHERE external_line_item_id = '601'",
    )
    assert (line["unit_cost"], line["cost_source"]) == (None, None)  # never a later cost


def test_amount_only_refunds_are_reversals(make_client, sim, admin_engine):
    store = sim.stores[HOST]
    store.refunds.append(
        {
            "id": 905,
            "parent_id": 500,
            "date_created_gmt": "2026-10-09T00:00:00",
            "amount": "5.00",
            "line_items": [],
            "shipping_lines": [],
            "fee_lines": [],
        }
    )
    _link(make_client, sim)
    (sale,) = _rows(
        admin_engine,
        "SELECT action, line_type, amount, tax_amount FROM sales_entries "
        "WHERE external_sale_id = 'refund-amount:905'",
    )
    assert sale == {
        "action": "return",
        "line_type": "adjustment",
        "amount": Decimal("-5"),
        "tax_amount": Decimal("0"),
    }


def test_unreadable_records_are_skipped_and_the_rest_imported(
    make_client, sim, admin_engine, caplog
):
    caplog.set_level(logging.WARNING)
    store = sim.stores[HOST]
    store.orders.append(
        {"id": 0, "status": "completed", "date_created_gmt": "2026-10-06T00:00:00"}
    )  # not a valid id
    store.orders.append(
        {"id": 510, "status": "completed", "date_created_gmt": "2026-10-06T00:00:00x"}
    )  # unreadable creation date
    _link(make_client, sim)
    assert [
        r["external_order_id"] for r in _rows(admin_engine, "SELECT external_order_id FROM orders")
    ] == ["500"]
    assert "woocommerce_records_skipped" in caplog.text


def test_the_check_for_changes_reads_only_what_changed(
    make_client, sim, clock, runtime, admin_engine
):
    _link(make_client, sim)
    before = len(sim.requests)
    clock.advance(timedelta(hours=1))
    store = sim.stores[HOST]
    store.products[0]["name"], store.products[0]["date_modified_gmt"] = (
        "Nitrile Gloves (box of 100)",
        (clock.now() - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1
    calls = sim.requests[before:]
    product_calls = [c for c in calls if c.url.path.endswith("/wc/v3/products")]
    assert product_calls and all("modified_after" in c.url.params for c in product_calls)
    order_calls = [c for c in calls if c.url.path.endswith("/wc/v3/orders")]
    assert all("modified_after" in c.url.params for c in order_calls)
    (title,) = _rows(admin_engine, "SELECT title FROM products WHERE external_product_id = '10'")
    assert title["title"] == "Nitrile Gloves (box of 100)"


def test_a_bad_cursor_ends_the_chain_with_an_error(make_client, sim, runtime):
    from app.providers.base.types import BulkKind
    from app.providers.woocommerce.client import UnexpectedResponseError

    provider = runtime.providers.get("woocommerce")
    ck, cs = sim.issue_key(HOST)
    secrets = {"store_url": f"https://{HOST}", "consumer_key": ck, "consumer_secret": cs}
    for cursor in ("not json", '{"s": "z"}', '{"s": "p", "pg": -1, "c": "AUD"}'):
        with pytest.raises(UnexpectedResponseError):
            provider.read_page(secrets, BulkKind.CATALOGUE, cursor)


def test_the_per_store_request_limit_pauses_the_import_instead_of_failing_it(
    make_client, runtime, admin_engine, clock
):
    from app.domains.commerce import importer
    from app.domains.jobs.service import ClaimedJob

    gentle = WooSim()
    sample_store(gentle.add_store(HOST))
    runtime.providers.register(build_provider(gentle, gentle=True))  # 2 per second, burst 4
    owner = _link(make_client, gentle)
    assert owner.store["status"] == "importing"  # paused, not failed
    (state,) = _rows(
        admin_engine, "SELECT store_id, import_job_id, last_error_code FROM commerce_sync_state"
    )
    assert state["last_error_code"] is None
    (job,) = _rows(
        admin_engine,
        "SELECT status, last_error_code FROM job_runs WHERE id = :j",
        j=state["import_job_id"],
    )
    assert (job["status"], job["last_error_code"]) == ("queued", "rate_limited")
    for _ in range(30):  # time passes; the retried steps finish the import
        clock.advance(timedelta(seconds=10))
        (state,) = _rows(admin_engine, "SELECT store_id, import_job_id FROM commerce_sync_state")
        if state["import_job_id"] is None:
            break
        importer.import_step(
            runtime,
            ClaimedJob(
                state["import_job_id"],
                uuid.UUID(owner.org),
                importer.JOB_IMPORT_STEP,
                str(state["store_id"]),
                2,
                5,
                None,
                None,
            ),
        )
    (store,) = _rows(admin_engine, "SELECT status FROM stores")
    assert store["status"] == "active"
