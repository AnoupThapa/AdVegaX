"""Keeping an imported store up to date (task 2A-07, PHASE_02A_PLAN §7, §9).

Webhooks say "object X changed" → the current object is fetched by id and upserted (bursts
coalesced, deletions handled, oversized objects reconciled); hourly and nightly
reconciliations run through the import chain; Shopify throttling backs off by cost; privacy
requests are carried out. Everything runs through the real API, database, job runner and the
Shopify simulator.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.commerce import importer, incremental
from app.domains.commerce.importer import SyncMode, enqueue_reconciliations
from app.providers.base.errors import RateLimitedError
from sqlalchemy import text

from tests.shopify_sim import (
    ShopifySim,
    build_provider,
    callback_params,
    money,
    sample_catalogue,
    sample_orders,
    webhook_request,
)

SHOP = "eve-zone.myshopify.com"
URL = "/api/v1/webhooks/shopify"


@pytest.fixture
def sim(runtime, clock):
    s = ShopifySim()
    s.add_shop(SHOP, catalogue=sample_catalogue(), orders=sample_orders())
    runtime.providers.register(build_provider(s, clock))
    return s


@pytest.fixture
def owner(make_client, sim, admin_engine):
    """An organization with the store connected, linked and imported."""
    c = make_client()
    c.signup("sync-owner@example.com")
    c.org = c.create_org("Sync Co")["id"]
    started = c.post(
        f"/organizations/{c.org}/connections/shopify/start", {"params": {"shop_domain": SHOP}}
    ).json()["data"]["authorize_url"]
    response = c.http.get(
        "/api/v1/connections/shopify/callback",
        params=callback_params(started),
        follow_redirects=False,
    )
    c.conn = parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]
    (resource,) = c.get(f"/organizations/{c.org}/connections/{c.conn}/resources").json()["data"]
    c.resource = resource["id"]
    c.post(f"/organizations/{c.org}/resources/{c.resource}/link")
    assert _one(admin_engine, "SELECT status FROM stores")["status"] == "active"
    sim.bulk_queries.clear()
    return c


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return db.execute(text(sql), params).mappings().all()


def _one(admin_engine, sql, **params):
    (row,) = _rows(admin_engine, sql, **params)
    return row


def _deliver(client, clock, topic, payload, webhook_id=None):
    headers, body = webhook_request(
        topic,
        payload,
        shop=SHOP,
        webhook_id=webhook_id or str(uuid.uuid4()),
        triggered_at=clock.now().isoformat(),
    )
    response = client.http.post(URL, content=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]["status"]


def _last_event(admin_engine):
    return _rows(admin_engine, "SELECT * FROM webhook_events ORDER BY received_at")[-1]


def _node(sim, node_id):
    nodes = sim.shops[SHOP].catalogue + sim.shops[SHOP].orders
    return next(n for n in nodes if n["id"] == node_id)


# ------------------------------------------------------------------ products
def test_product_update_fetches_the_current_product(owner, client, sim, clock, admin_engine):
    product = _node(sim, "gid://shopify/Product/1")
    product["title"], product["updatedAt"] = "Nitrile Gloves (Blue)", "2026-10-12T00:00:00Z"
    variant = _node(sim, "gid://shopify/ProductVariant/11")
    variant["price"], variant["updatedAt"] = "18.50", "2026-10-12T00:00:00Z"
    # The webhook body says something else entirely: it is never used as data.
    _deliver(client, clock, "products/update", {"id": 1, "title": "IGNORED"})
    assert sim.fetches == [("product", "gid://shopify/Product/1")]
    title = _one(admin_engine, "SELECT title FROM products WHERE handle = 'nitrile-gloves'")
    assert title["title"] == "Nitrile Gloves (Blue)"
    price = _one(admin_engine, "SELECT price FROM product_variants WHERE sku = 'NG-M'")
    assert price["price"] == Decimal("18.50")
    event = _last_event(admin_engine)
    assert (event["status"], event["object_external_id"]) == (
        "processed",
        "gid://shopify/Product/1",
    )


def test_inventory_update_refreshes_the_variant_through_its_product(
    owner, client, sim, clock, admin_engine
):
    variant = _node(sim, "gid://shopify/ProductVariant/11")
    variant["inventoryQuantity"], variant["updatedAt"] = 95, "2026-10-12T00:00:00Z"
    _deliver(client, clock, "inventory_levels/update", {"inventory_item_id": 111, "available": 1})
    assert sim.fetches == [("product", "gid://shopify/Product/1")]
    stock = _one(admin_engine, "SELECT inventory_available FROM product_variants WHERE sku='NG-M'")
    assert stock["inventory_available"] == 95  # the summed quantity, not the webhook's level


def test_unknown_inventory_item_is_left_to_its_product_webhook(
    owner, client, sim, clock, admin_engine
):
    _deliver(client, clock, "inventory_levels/update", {"inventory_item_id": 999})
    assert sim.fetches == []
    assert _last_event(admin_engine)["error_code"] == "unknown_inventory_item"


def test_product_delete_marks_it_deleted_and_keeps_order_history(
    owner, client, sim, clock, admin_engine
):
    _deliver(client, clock, "products/delete", {"id": 1})
    assert sim.fetches == []  # nothing to fetch for a deletion
    product = _one(admin_engine, "SELECT id, status FROM products WHERE handle = 'nitrile-gloves'")
    assert product["status"] == "deleted"
    variants = _rows(
        admin_engine, "SELECT deleted FROM product_variants WHERE product_id = :p", p=product["id"]
    )
    assert {v["deleted"] for v in variants} == {True}
    line = _one(
        admin_engine,
        "SELECT variant_id FROM order_items WHERE external_line_item_id = :l",
        l="gid://shopify/LineItem/601",
    )
    assert line["variant_id"] is not None


def test_bursts_for_one_object_are_coalesced(owner, client, sim, clock, runtime, admin_engine):
    queued = []
    original = runtime.enqueue_job
    runtime.enqueue_job = lambda job_id, delay=0: queued.append(job_id)
    try:
        for _ in range(3):
            _deliver(client, clock, "products/update", {"id": 1})
    finally:
        runtime.enqueue_job = original
    assert len(queued) == 1
    statuses = [
        (e["status"], e["error_code"])
        for e in _rows(admin_engine, "SELECT * FROM webhook_events ORDER BY received_at")
    ]
    assert statuses[1:] == [("ignored", "coalesced"), ("ignored", "coalesced")]
    from app.workers.job_tasks import run_job_now

    run_job_now(queued[0])
    assert sim.fetches == [("product", "gid://shopify/Product/1")]  # one fetch for three


def test_a_new_delivery_after_the_fetch_started_is_fetched_again(owner, client, sim, clock):
    _deliver(client, clock, "products/update", {"id": 1})
    _deliver(client, clock, "products/update", {"id": 1})
    assert len(sim.fetches) == 2  # eager jobs: the first fetch had already run


# ------------------------------------------------------------------ orders
def _new_order(sim, number=600, processed="2026-10-12T02:00:00Z"):
    order = copy.deepcopy(_node(sim, "gid://shopify/Order/500"))
    oid = f"gid://shopify/Order/{number}"
    order.update(id=oid, name=f"#{number}", processedAt=processed, updatedAt=processed, refunds=[])
    order["totalPriceSet"] = money("39.80")
    nodes = [
        order,
        {
            "id": f"gid://shopify/LineItem/{number}1",
            "title": "Nitrile Gloves - Medium",
            "sku": "NG-M",
            "quantity": 2,
            "variant": {"id": "gid://shopify/ProductVariant/11"},
            "originalUnitPriceSet": money("19.90"),
            "__parentId": oid,
        },
        {
            "id": f"gid://shopify/SalesAgreement/{number}2",
            "happenedAt": processed,
            "reason": "ORDER",
            "__parentId": oid,
        },
        {
            "id": f"gid://shopify/Sale/{number}3",
            "actionType": "ORDER",
            "lineType": "PRODUCT",
            "quantity": 2,
            "totalAmount": money("39.80"),
            "totalDiscountAmountBeforeTaxes": money("0.00"),
            "totalTaxAmount": money("3.62"),
            "lineItem": {"id": f"gid://shopify/LineItem/{number}1"},
            "__parentId": f"gid://shopify/SalesAgreement/{number}2",
        },
    ]
    sim.shops[SHOP].orders.extend(nodes)
    return oid


def test_new_order_takes_the_cost_valid_at_order_time(owner, client, sim, clock, admin_engine):
    oid = _new_order(sim, processed=clock.now().isoformat())
    _deliver(client, clock, "orders/create", {"id": 600, "admin_graphql_api_id": oid})
    line = _one(
        admin_engine,
        "SELECT unit_cost, cost_source FROM order_items WHERE external_line_item_id = :l",
        l="gid://shopify/LineItem/6001",
    )
    assert (line["unit_cost"], line["cost_source"]) == (Decimal("7.25"), "order_time")
    sale = _one(
        admin_engine,
        "SELECT order_item_id FROM sales_entries WHERE external_sale_id = :s",
        s="gid://shopify/Sale/6003",
    )
    assert sale["order_item_id"] is not None
    order = _one(
        admin_engine, "SELECT gross_amount FROM orders WHERE external_order_id = :o", o=oid
    )
    assert order["gross_amount"] == Decimal("39.80")


def test_refund_webhook_refetches_its_order(owner, client, sim, clock, admin_engine):
    order = _node(sim, "gid://shopify/Order/500")
    order["updatedAt"] = "2026-10-12T00:00:00Z"
    order["refunds"].append(
        {
            "id": "gid://shopify/Refund/901",
            "createdAt": "2026-10-12T00:00:00Z",
            "totalRefundedSet": money("10.00"),
        }
    )
    _deliver(client, clock, "refunds/create", {"id": 901, "order_id": 500})
    assert sim.fetches == [("order", "gid://shopify/Order/500")]
    refunds = _rows(admin_engine, "SELECT external_refund_id FROM refunds ORDER BY processed_at")
    assert [r["external_refund_id"] for r in refunds] == [
        "gid://shopify/Refund/900",
        "gid://shopify/Refund/901",
    ]


def test_order_delete_removes_it_with_its_rows(owner, client, sim, clock, admin_engine):
    _deliver(client, clock, "orders/delete", {"id": 500})
    for table in ("orders", "order_items", "sales_entries", "refunds"):
        assert _one(admin_engine, f"SELECT count(*) AS n FROM {table}")["n"] == 0


def test_order_not_visible_to_the_app_is_left_alone(owner, client, sim, clock, admin_engine):
    _deliver(client, clock, "orders/updated", {"id": 4242})
    assert _last_event(admin_engine)["error_code"] == "not_found"
    assert _one(admin_engine, "SELECT count(*) AS n FROM orders")["n"] == 1


def test_large_object_is_applied_then_reconciled(owner, client, sim, clock, admin_engine):
    sim.page_limit = 1  # the order has two lines: the fetch is incomplete
    order = _node(sim, "gid://shopify/Order/500")
    order["updatedAt"] = "2026-10-12T00:00:00Z"
    _deliver(client, clock, "orders/updated", {"id": 500})
    assert _last_event(admin_engine)["error_code"] == "partial_reconcile_requested"
    assert any("updated_at:>=" in q for q in sim.bulk_queries)  # a reconciliation ran
    state = _one(admin_engine, "SELECT sync_mode, import_job_id FROM commerce_sync_state")
    assert (state["sync_mode"], state["import_job_id"]) == (None, None)


def test_shop_and_bulk_notices_need_no_fetch(owner, client, sim, clock, admin_engine):
    _deliver(client, clock, "shop/update", {"id": 1})
    assert (_last_event(admin_engine)["status"], sim.fetches) == ("processed", [])


def test_webhooks_wait_while_the_store_is_still_importing(
    make_client, client, sim, clock, runtime, admin_engine
):
    c = make_client()
    c.signup("importing@example.com")
    c.org = c.create_org("Importing Co")["id"]
    started = c.post(
        f"/organizations/{c.org}/connections/shopify/start", {"params": {"shop_domain": SHOP}}
    ).json()["data"]["authorize_url"]
    response = c.http.get(
        "/api/v1/connections/shopify/callback",
        params=callback_params(started),
        follow_redirects=False,
    )
    conn = parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]
    (resource,) = c.get(f"/organizations/{c.org}/connections/{conn}/resources").json()["data"]
    original = runtime.enqueue_job
    runtime.enqueue_job = lambda job_id, delay=0: None  # the import never progresses
    c.post(f"/organizations/{c.org}/resources/{resource['id']}/link")
    runtime.enqueue_job = original
    _deliver(client, clock, "products/update", {"id": 1})
    assert _last_event(admin_engine)["error_code"] == "import_pending"
    assert sim.fetches == []


# ------------------------------------------------------------------ reconciliation
def test_hourly_reconciliation_fetches_changes_since_the_last_run(
    owner, sim, clock, runtime, admin_engine
):
    before = _one(admin_engine, "SELECT last_reconciled_at FROM commerce_sync_state")
    clock.advance(timedelta(hours=1))
    product = _node(sim, "gid://shopify/Product/1")
    product["title"], product["updatedAt"] = "Gloves v2", "2026-10-12T00:00:00Z"
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1
    since = (before["last_reconciled_at"] - timedelta(minutes=10)).astimezone(UTC)
    stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert f"updated_at:>='{stamp}'" in sim.bulk_queries[0]
    assert f"updated_at:>='{stamp}'" in sim.bulk_queries[1]
    assert "created_at:>=" in sim.bulk_queries[1]  # still within the history window
    assert (
        _one(admin_engine, "SELECT title FROM products WHERE handle='nitrile-gloves'")["title"]
        == "Gloves v2"
    )
    after = _one(admin_engine, "SELECT * FROM commerce_sync_state")
    assert after["last_reconciled_at"] == clock.now()
    assert after["last_deep_reconciled_at"] is None
    audits = _rows(admin_engine, "SELECT action FROM audit_logs WHERE action LIKE 'store.%'")
    assert "store.sync_started" not in [a["action"] for a in audits]  # scheduled runs: no noise


def test_nightly_deep_check_reads_the_whole_catalogue_and_recent_orders(
    owner, sim, clock, runtime, admin_engine
):
    assert enqueue_reconciliations(runtime, SyncMode.DEEP) == 1
    catalogue, orders = sim.bulk_queries
    assert "(query:" not in catalogue
    recent = (clock.now() - timedelta(days=30)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert f"created_at:>='{recent}'" in orders
    state = _one(admin_engine, "SELECT last_deep_reconciled_at FROM commerce_sync_state")
    assert state["last_deep_reconciled_at"] == clock.now()


def test_reconciliation_skips_a_running_chain_but_restarts_a_stale_one(
    owner, sim, clock, runtime, admin_engine
):
    original = runtime.enqueue_job
    runtime.enqueue_job = lambda job_id, delay=0: None
    try:
        assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1  # starts, never runs
        assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 0  # still "running"
        clock.advance(timedelta(hours=7))  # silent longer than COMMERCE_CHAIN_STALE_AFTER
        assert enqueue_reconciliations(runtime, SyncMode.DEEP) == 1
    finally:
        runtime.enqueue_job = original
    assert _one(admin_engine, "SELECT sync_mode FROM commerce_sync_state")["sync_mode"] == "deep"


def test_sync_now_runs_a_deep_check(owner, sim, admin_engine):
    response = owner.post(f"/organizations/{owner.org}/resources/{owner.resource}/sync")
    assert response.status_code == 202
    assert "(query:" not in sim.bulk_queries[0]  # whole catalogue
    actions = [r["action"] for r in _rows(admin_engine, "SELECT action FROM audit_logs")]
    assert "store.sync_started" in actions


def test_reconciliation_schedules(runtime):
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert schedule["commerce-reconcile"]["task"] == "advegax.schedule.commerce_reconcile"
    assert schedule["commerce-deep"]["schedule"] == 24 * 3600


def test_scheduled_tasks_run_once_per_tick(owner, runtime):
    from app.workers import job_tasks

    runtime.redis.delete("schedule-lock:commerce_reconcile", "schedule-lock:commerce_deep")
    assert job_tasks.commerce_reconcile_task() == 1
    assert job_tasks.commerce_reconcile_task() is None
    assert job_tasks.commerce_deep_task() == 1


# ------------------------------------------------------------------ throttling
def test_throttled_calls_back_off_by_query_cost(owner, client, sim, clock, runtime):
    sim.throttle_next = 1
    provider = runtime.providers.get("shopify")
    secrets = {"shop": SHOP, "access_token": "shpat_sim_access_1"}
    with pytest.raises(RateLimitedError) as caught:
        provider.fetch_product(secrets, "gid://shopify/Product/1")
    assert caught.value.retry_after_seconds == pytest.approx(5.0)  # (502 - 2) / 100 per second


@pytest.mark.parametrize(
    ("body", "wait"),
    [
        ({}, 1.0),
        ({"extensions": {"cost": {"requestedQueryCost": 50}}}, 1.0),
        (
            {
                "extensions": {
                    "cost": {
                        "requestedQueryCost": 50,
                        "throttleStatus": {"currentlyAvailable": 60, "restoreRate": 50},
                    }
                }
            },
            1.0,
        ),
        (
            {
                "extensions": {
                    "cost": {
                        "requestedQueryCost": 1000,
                        "throttleStatus": {"currentlyAvailable": 0, "restoreRate": 0},
                    }
                }
            },
            60.0,
        ),
        (
            {
                "extensions": {
                    "cost": {
                        "requestedQueryCost": 100000,
                        "throttleStatus": {"currentlyAvailable": 0, "restoreRate": 50},
                    }
                }
            },
            60.0,
        ),
        ({"extensions": {"cost": {"throttleStatus": {"currentlyAvailable": "x"}}}}, 1.0),
    ],
)
def test_throttle_wait_is_bounded(body, wait):
    from app.providers.shopify.admin_api import throttle_wait

    assert throttle_wait(body) == wait


# ------------------------------------------------------------------ costs
def test_cost_at_order_time_rules():
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    history = [
        (t0, Decimal("7.25")),
        (t0 + timedelta(days=5), None),
        (t0 + timedelta(days=9), Decimal("8")),
    ]
    cost_for = importer._cost_for
    assert cost_for([], t0) == (None, None)
    assert cost_for(history, t0 - timedelta(days=1)) == (Decimal("7.25"), "import_time")
    assert cost_for(history, t0 + timedelta(days=1)) == (Decimal("7.25"), "order_time")
    assert cost_for(history, t0 + timedelta(days=6)) == (None, None)  # cost removed: unknown
    assert cost_for(history, t0 + timedelta(days=10)) == (Decimal("8"), "order_time")
    assert cost_for([(t0, None)], t0 - timedelta(days=1)) == (None, None)


# ------------------------------------------------------------------ privacy
def test_shop_redact_is_not_applied_to_a_reconnected_store(owner, client, clock, admin_engine):
    _deliver(client, clock, "shop/redact", {"shop_id": 1, "shop_domain": SHOP})
    event = _last_event(admin_engine)
    assert (event["status"], event["error_code"]) == ("ignored", "store_reconnected")
    assert _one(admin_engine, "SELECT count(*) AS n FROM stores")["n"] == 1
    actions = [r["action"] for r in _rows(admin_engine, "SELECT action FROM audit_logs")]
    assert "privacy.shop_redact_skipped" in actions


def test_shop_redact_erases_all_store_data_after_uninstall(owner, client, clock, admin_engine):
    _deliver(client, clock, "app/uninstalled", {"id": 1})
    clock.advance(timedelta(hours=48))
    _deliver(client, clock, "shop/redact", {"shop_id": 1, "shop_domain": SHOP})
    for table in (
        "stores",
        "products",
        "product_variants",
        "product_cost_history",
        "orders",
        "order_items",
        "sales_entries",
        "refunds",
        "commerce_sync_state",
    ):
        assert _one(admin_engine, f"SELECT count(*) AS n FROM {table}")["n"] == 0, table
    event = _last_event(admin_engine)
    assert (event["status"], event["error_code"]) == ("processed", "store_data_erased")
    metadata = _rows(
        admin_engine,
        "SELECT metadata FROM audit_logs WHERE action = 'privacy.shop_redacted'",
    )[0]["metadata"]
    assert metadata["counts"] == {"stores": 1, "orders": 1, "products": 2}


def test_replayed_privacy_job_does_nothing_twice(owner, client, clock, runtime, admin_engine):
    from app.domains.commerce import privacy
    from app.domains.jobs.service import ClaimedJob

    _deliver(client, clock, "customers/redact", {"shop_domain": SHOP, "customer": {"id": 5}})
    event = _last_event(admin_engine)
    job = ClaimedJob(
        uuid.uuid4(),
        uuid.UUID(owner.org),
        privacy.JOB_CUSTOMER_REDACT,
        str(event["id"]),
        1,
        5,
        None,
        None,
    )
    privacy.customer_redact(runtime, job)
    actions = [r["action"] for r in _rows(admin_engine, "SELECT action FROM audit_logs")]
    assert actions.count("privacy.customer_redacted") == 1


def test_object_job_for_a_missing_event_is_dropped(runtime):
    from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError

    for subject in (None, str(uuid.uuid4())):
        job = ClaimedJob(
            uuid.uuid4(), uuid.uuid4(), incremental.JOB_OBJECT_CHANGED, subject, 1, 5, None, None
        )
        with pytest.raises(JobSubjectGoneError):
            incremental.object_changed(runtime, job)


def test_permanent_fetch_errors_mark_the_event_failed(owner, client, sim, clock, admin_engine):
    sim.graphql_status = 400
    _deliver(client, clock, "products/update", {"id": 1})
    event = _last_event(admin_engine)
    assert (event["status"], event["error_code"]) == ("failed", "invalid_request")


def test_unlinked_store_ignores_webhooks(owner, client, sim, clock, admin_engine):
    owner.post(f"/organizations/{owner.org}/resources/{owner.resource}/unlink")
    _deliver(client, clock, "products/update", {"id": 1})
    assert _last_event(admin_engine)["error_code"] == "store_not_syncing"
    assert sim.fetches == []
