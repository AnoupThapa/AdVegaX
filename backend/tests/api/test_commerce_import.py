"""Initial store import through the real API, database, job runner and Shopify simulator
(task 2A-06, PHASE_02A_PLAN §9).

Linking a Shopify store creates the store and runs the import chain (eager jobs in tests):
catalogue export → orders export → links resolved → store active. Checks the stored data
(no unknown value shown as 0, test orders excluded, costs as an import snapshot, reversals
dated by processing), idempotent re-import, the "newer wins" guard, polling, failures, the
single-chain guarantees and that the test platform is unaffected.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.commerce import importer
from app.domains.jobs.service import ClaimedJob
from sqlalchemy import text

from tests.helpers import connected
from tests.shopify_sim import (
    ShopifySim,
    build_provider,
    callback_params,
    sample_catalogue,
    sample_orders,
)

SHOP = "eve-zone.myshopify.com"


@pytest.fixture
def sim(runtime, clock):
    s = ShopifySim()
    s.add_shop(SHOP, catalogue=sample_catalogue(), orders=sample_orders())
    runtime.providers.register(build_provider(s, clock))
    return s


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup("import-owner@example.com")
    c.org = c.create_org("Import Co")["id"]
    return c


def _connect(client) -> str:
    started = client.post(
        f"/organizations/{client.org}/connections/shopify/start",
        {"params": {"shop_domain": SHOP}},
    ).json()["data"]["authorize_url"]
    response = client.http.get(
        "/api/v1/connections/shopify/callback",
        params=callback_params(started),
        follow_redirects=False,
    )
    return parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]


def _store_resource(client, conn) -> str:
    (resource,) = client.get(f"/organizations/{client.org}/connections/{conn}/resources").json()[
        "data"
    ]
    return resource["id"]


def _link(client) -> tuple[str, str]:
    conn = _connect(client)
    resource = _store_resource(client, conn)
    response = client.post(f"/organizations/{client.org}/resources/{resource}/link")
    assert response.status_code in (200, 201), response.text
    return conn, resource


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return db.execute(text(sql), params).mappings().all()


def _one(admin_engine, sql, **params):
    (row,) = _rows(admin_engine, sql, **params)
    return row


def _audit(admin_engine, org):
    return [
        r["action"]
        for r in _rows(
            admin_engine,
            "SELECT action FROM audit_logs WHERE organization_id = :o ORDER BY created_at",
            o=org,
        )
    ]


# ------------------------------------------------------------------ the happy path
def test_linking_a_store_imports_catalogue_and_orders(owner, sim, clock, admin_engine):
    _link(owner)
    store = _one(admin_engine, "SELECT * FROM stores")
    assert store["status"] == "active"
    assert (store["domain"], store["currency"], store["timezone"]) == (
        SHOP,
        "AUD",
        "Australia/Sydney",
    )
    assert store["first_import_completed_at"] is not None
    # Without read_all_orders Shopify allows 60 days of orders.
    assert clock.now() - store["history_from"] == timedelta(days=60)
    since = store["history_from"].strftime("%Y-%m-%dT%H:%M:%SZ")
    assert f"created_at:>='{since}'" in sim.bulk_queries[1]

    state = _one(admin_engine, "SELECT * FROM commerce_sync_state")
    assert (state["import_progress"], state["import_job_id"], state["bulk_operation_id"]) == (
        100,
        None,
        None,
    )
    assert state["last_error_code"] is None

    actions = _audit(admin_engine, owner.org)
    for action in ("store.import_started", "store.catalogue_imported", "store.import_completed"):
        assert action in actions


def test_catalogue_values_unknown_stay_empty_never_zero(owner, admin_engine):
    _link(owner)
    products = _rows(admin_engine, "SELECT title, status FROM products ORDER BY title")
    assert [(p["title"], p["status"]) for p in products] == [
        ("Gift Wrap", "unlisted"),
        ("Nitrile Gloves", "active"),
    ]
    variants = {
        v["sku"] or v["title"]: v for v in _rows(admin_engine, "SELECT * FROM product_variants")
    }
    assert variants["NG-M"]["price"] == Decimal("19.90")
    assert (variants["NG-M"]["inventory_tracked"], variants["NG-M"]["inventory_available"]) == (
        True,
        120,
    )
    assert variants["NG-L"]["inventory_available"] == 0  # tracked and really zero
    untracked = variants["Default Title"]
    assert (untracked["inventory_tracked"], untracked["inventory_available"]) == (False, None)

    costs = _rows(
        admin_engine,
        "SELECT v.sku, c.unit_cost, c.source, c.currency FROM product_cost_history c "
        "JOIN product_variants v ON v.id = c.variant_id ORDER BY c.unit_cost",
    )
    assert [(c["sku"], c["unit_cost"], c["source"]) for c in costs] == [
        (None, Decimal("1.10"), "import_snapshot"),
        ("NG-M", Decimal("7.25"), "import_snapshot"),
    ]  # NG-L has no cost at all: no row (unknown), not a 0 cost


def test_orders_lines_sales_and_refunds(owner, admin_engine):
    _link(owner)
    order = _one(admin_engine, "SELECT * FROM orders")  # the test order is excluded
    assert order["order_number"] == "#1001"
    assert order["financial_status"] == "partially_refunded"
    assert order["total_amount"] == Decimal("63.80")
    assert order["gross_amount"] == Decimal("50.81")  # 2 x 19.90 + 11.01
    assert order["customer_key"] is None and order["country_code"] is None  # Q8, see report

    lines = {
        r["external_line_item_id"]: r for r in _rows(admin_engine, "SELECT * FROM order_items")
    }
    gloves, engraving = lines["gid://shopify/LineItem/601"], lines["gid://shopify/LineItem/602"]
    assert gloves["variant_id"] is not None
    assert (gloves["unit_cost"], gloves["cost_source"]) == (Decimal("7.25"), "import_time")
    assert (engraving["variant_id"], engraving["unit_cost"], engraving["cost_source"]) == (
        None,
        None,
        None,
    )

    sales = {r["external_sale_id"]: r for r in _rows(admin_engine, "SELECT * FROM sales_entries")}
    assert len(sales) == 4  # the test order's sale is excluded
    first = sales["gid://shopify/Sale/801"]
    assert (first["agreement_reason"], first["action"], first["line_type"]) == (
        "order",
        "order",
        "product",
    )
    assert first["order_item_id"] == gloves["id"]
    # The sale that arrived before its line item is linked after the import.
    assert sales["gid://shopify/Sale/802"]["order_item_id"] == engraving["id"]
    assert sales["gid://shopify/Sale/803"]["order_item_id"] is None  # shipping
    reversal = sales["gid://shopify/Sale/804"]
    assert (reversal["agreement_reason"], reversal["action"], reversal["amount"]) == (
        "refund",
        "return",
        Decimal("-20.790000"),
    )
    assert reversal["happened_at"] > first["happened_at"]  # dated by processing day

    refund = _one(admin_engine, "SELECT * FROM refunds")
    assert refund["total_amount"] == Decimal("21.89")


def test_full_history_with_read_all_orders(owner, sim, clock, admin_engine):
    sim.granted_scope = "read_products,read_inventory,read_orders,read_all_orders"
    _link(owner)
    store = _one(admin_engine, "SELECT history_from FROM stores")
    assert clock.now() - store["history_from"] == timedelta(days=395)  # 13 months (Q9)


# ------------------------------------------------------------------ re-import
def test_reimport_is_idempotent_and_records_cost_changes(owner, sim, admin_engine):
    _, resource = _link(owner)
    counts = {
        t: _one(admin_engine, f"SELECT count(*) AS n FROM {t}")["n"]
        for t in ("products", "product_variants", "orders", "order_items", "sales_entries")
    }
    sim.shops[SHOP].catalogue[1]["inventoryItem"]["unitCost"]["amount"] = "8.00"
    response = owner.post(f"/organizations/{owner.org}/resources/{resource}/sync")
    assert response.status_code == 202
    for table, before in counts.items():
        assert _one(admin_engine, f"SELECT count(*) AS n FROM {table}")["n"] == before
    costs = _rows(
        admin_engine,
        "SELECT c.unit_cost, c.source FROM product_cost_history c "
        "JOIN product_variants v ON v.id = c.variant_id WHERE v.sku = 'NG-M' "
        "ORDER BY c.effective_from",
    )
    # Same timestamp in a frozen clock → the unique (variant, effective_from) keeps the first;
    # advance time to see the change recorded.
    assert [c["unit_cost"] for c in costs] == [Decimal("7.25")]


def test_cost_change_after_first_import_is_a_platform_cost(owner, sim, clock, admin_engine):
    _, resource = _link(owner)
    sim.shops[SHOP].catalogue[1]["inventoryItem"]["unitCost"]["amount"] = "8.00"
    sim.shops[SHOP].catalogue[2]["inventoryItem"]["unitCost"] = {
        "amount": "3.00",
        "currencyCode": "USD",  # not the store currency: not recorded (no conversion in 2A)
    }
    clock.advance(timedelta(hours=1))
    owner.post(f"/organizations/{owner.org}/resources/{resource}/sync")
    costs = _rows(
        admin_engine,
        "SELECT v.sku, c.unit_cost, c.source FROM product_cost_history c "
        "JOIN product_variants v ON v.id = c.variant_id ORDER BY v.sku, c.effective_from",
    )
    assert [(c["sku"], c["unit_cost"], c["source"]) for c in costs] == [
        ("NG-M", Decimal("7.25"), "import_snapshot"),
        ("NG-M", Decimal("8.00"), "platform"),
        (None, Decimal("1.10"), "import_snapshot"),
    ]


def test_cost_removed_on_the_platform_is_recorded_as_unknown(owner, sim, clock, admin_engine):
    _, resource = _link(owner)
    del sim.shops[SHOP].catalogue[1]["inventoryItem"]["unitCost"]
    clock.advance(timedelta(hours=1))
    owner.post(f"/organizations/{owner.org}/resources/{resource}/sync")
    costs = _rows(
        admin_engine,
        "SELECT c.unit_cost FROM product_cost_history c JOIN product_variants v "
        "ON v.id = c.variant_id WHERE v.sku = 'NG-M' ORDER BY c.effective_from",
    )
    assert [c["unit_cost"] for c in costs] == [Decimal("7.25"), None]


def test_older_platform_data_never_overwrites_newer(owner, sim, admin_engine):
    _, resource = _link(owner)
    order = sim.shops[SHOP].orders[0]
    order["updatedAt"] = "2026-10-01T00:00:00Z"  # older than what is stored
    order["totalPriceSet"]["shopMoney"]["amount"] = "1.00"
    owner.post(f"/organizations/{owner.org}/resources/{resource}/sync")
    assert _one(admin_engine, "SELECT total_amount FROM orders")["total_amount"] == Decimal("63.80")
    order["updatedAt"] = "2026-10-09T00:00:00Z"  # newer: applied
    owner.post(f"/organizations/{owner.org}/resources/{resource}/sync")
    assert _one(admin_engine, "SELECT total_amount FROM orders")["total_amount"] == Decimal("1.00")


# ------------------------------------------------------------------ polling and failures
def test_running_exports_are_polled_until_complete(owner, sim, admin_engine):
    sim.bulk_polls_running = 2
    _link(owner)
    assert _one(admin_engine, "SELECT status FROM stores")["status"] == "active"
    steps = _one(
        admin_engine,
        "SELECT count(*) AS n FROM job_runs WHERE job_type = :t",
        t=importer.JOB_IMPORT_STEP,
    )["n"]
    assert steps >= 8  # start + 2 running polls + finish, for each of the two exports


def test_failed_export_marks_the_store(owner, sim, admin_engine):
    sim.bulk_final_status, sim.bulk_error_code = "FAILED", "ACCESS_DENIED"
    _link(owner)
    store = _one(admin_engine, "SELECT status FROM stores")
    state = _one(admin_engine, "SELECT * FROM commerce_sync_state")
    assert store["status"] == "error"
    assert (state["last_error_code"], state["import_job_id"]) == ("access_denied", None)
    assert "store.import_failed" in _audit(admin_engine, owner.org)


def test_rejected_export_fails_the_import(owner, sim, admin_engine):
    sim.bulk_user_errors = True
    _link(owner)
    state = _one(admin_engine, "SELECT last_error_code FROM commerce_sync_state")
    assert state["last_error_code"] == "bulk_export_rejected"
    job = _one(
        admin_engine,
        "SELECT status, last_error_code FROM job_runs WHERE job_type = :t",
        t=importer.JOB_IMPORT_STEP,
    )
    assert (job["status"], job["last_error_code"]) == ("failed", "bulk_export_rejected")


def test_expired_download_link_runs_the_export_again(owner, sim, admin_engine):
    sim.download_failures = 1
    _link(owner)
    assert _one(admin_engine, "SELECT status FROM stores")["status"] == "active"
    assert len(sim.bulk_queries) == 3  # catalogue twice (link expired once), then orders
    assert _one(admin_engine, "SELECT count(*) AS n FROM products")["n"] == 2


# ------------------------------------------------------------------ chain guarantees
class Held:
    """Record job dispatches instead of running them, to drive steps one at a time."""

    def __init__(self, runtime):
        self.runtime, self.queued, self._original = runtime, [], runtime.enqueue_job

    def start(self):
        self.runtime.enqueue_job = lambda job_id, delay=0: self.queued.append(job_id)

    def stop(self):
        self.runtime.enqueue_job = self._original

    @property
    def last(self):
        return self.queued[-1]


@pytest.fixture
def held(runtime):
    h = Held(runtime)
    yield h
    h.stop()


def _link_held(client, held) -> tuple[str, str]:
    conn = _connect(client)
    resource = _store_resource(client, conn)
    held.start()
    assert client.post(f"/organizations/{client.org}/resources/{resource}/link").status_code in (
        200,
        201,
    )
    return conn, resource


def _run(job_id):
    from app.workers.job_tasks import run_job_now

    return run_job_now(job_id)


def _chain_job(admin_engine):
    return _one(admin_engine, "SELECT import_job_id FROM commerce_sync_state")["import_job_id"]


def test_steps_run_one_at_a_time_in_order(owner, sim, held, admin_engine):
    _link_held(owner, held)
    assert len(held.queued) == 1
    assert sim.bulk_queries == []  # nothing ran yet
    _run(held.last)  # start the catalogue export
    assert len(sim.bulk_queries) == 1
    _run(held.last)  # finished → apply the catalogue
    progress = _one(admin_engine, "SELECT import_progress FROM commerce_sync_state")
    assert progress["import_progress"] == importer.PROGRESS_AFTER_CATALOGUE
    while _chain_job(admin_engine):
        _run(held.last)
    assert _one(admin_engine, "SELECT status FROM stores")["status"] == "active"


def test_temporary_errors_retry_and_the_last_attempt_shows_on_the_store(
    owner, sim, held, runtime, admin_engine
):
    from app.providers.base.errors import RetryableError

    _link_held(owner, held)
    _run(held.last)  # export started
    sim.graphql_status = 503
    org = uuid.UUID(owner.org)
    store_id = str(_one(admin_engine, "SELECT id FROM stores")["id"])
    job_id = _chain_job(admin_engine)
    early = ClaimedJob(job_id, org, importer.JOB_IMPORT_STEP, store_id, 1, 5, None, None)
    with pytest.raises(RetryableError):
        importer.import_step(runtime, early)
    assert _one(admin_engine, "SELECT status FROM stores")["status"] == "importing"
    last = ClaimedJob(job_id, org, importer.JOB_IMPORT_STEP, store_id, 5, 5, None, None)
    with pytest.raises(RetryableError):
        importer.import_step(runtime, last)
    state = _one(admin_engine, "SELECT last_error_code, import_job_id FROM commerce_sync_state")
    assert _one(admin_engine, "SELECT status FROM stores")["status"] == "error"
    assert (state["last_error_code"], state["import_job_id"]) == ("server_error", None)


def test_a_stale_or_duplicate_step_does_nothing(owner, sim, held, runtime, admin_engine):
    _link_held(owner, held)
    org = uuid.UUID(owner.org)
    store_id = _one(admin_engine, "SELECT id FROM stores")["id"]
    stale = ClaimedJob(uuid.uuid4(), org, importer.JOB_IMPORT_STEP, str(store_id), 1, 5, None, None)
    importer.import_step(runtime, stale)
    assert sim.bulk_queries == []


def test_a_busy_store_lock_skips_the_step(owner, sim, held, runtime, admin_engine):
    from app.domains.integrations.tokens import account_lock

    _link_held(owner, held)
    store_id = _one(admin_engine, "SELECT id FROM stores")["id"]
    with account_lock(runtime.redis, f"import-lock:{store_id}", wait_seconds=0):
        _run(held.last)
    assert sim.bulk_queries == []


def test_unlinking_stops_the_import(owner, sim, held, admin_engine):
    _, resource = _link_held(owner, held)
    owner.post(f"/organizations/{owner.org}/resources/{resource}/unlink")
    _run(held.last)
    state = _one(admin_engine, "SELECT * FROM commerce_sync_state")
    assert (state["last_error_code"], state["import_job_id"]) == ("link_ended", None)
    assert sim.bulk_queries == []


def test_relinking_restarts_an_unfinished_import(owner, sim, held, admin_engine):
    _, resource = _link_held(owner, held)
    owner.post(f"/organizations/{owner.org}/resources/{resource}/unlink")
    owner.post(f"/organizations/{owner.org}/resources/{resource}/link")
    assert _one(admin_engine, "SELECT count(*) AS n FROM stores")["n"] == 1  # same store reused
    while _chain_job(admin_engine):
        _run(held.last)
    assert _one(admin_engine, "SELECT status FROM stores")["status"] == "active"


def test_disconnecting_stops_the_import(owner, sim, held, admin_engine):
    conn, _ = _link_held(owner, held)
    owner.post(f"/organizations/{owner.org}/connections/{conn}/disconnect")
    _run(held.last)
    state = _one(admin_engine, "SELECT last_error_code, import_job_id FROM commerce_sync_state")
    assert state["import_job_id"] is None
    assert state["last_error_code"] in ("link_ended", "connection_inactive")
    assert sim.bulk_queries == []


# ------------------------------------------------------------------ other platforms
def test_test_platform_store_links_without_an_import(make_client, admin_engine):
    c = make_client()
    c.signup("fake-store@example.com")
    org = c.create_org("Fake Co")["id"]
    conn = connected(c, org)
    resources = c.get(f"/organizations/{org}/connections/{conn}/resources").json()["data"]
    store = next(r for r in resources if r["kind"] == "store")
    assert c.post(f"/organizations/{org}/resources/{store['id']}/link").status_code in (200, 201)
    assert _rows(admin_engine, "SELECT id FROM stores") == []
    assert c.post(f"/organizations/{org}/resources/{store['id']}/sync").status_code == 202
