"""Keeping WooCommerce stores up to date and healthy (task 2B-06, PHASE_02B_PLAN §6.6, §9).

WooCommerce has no webhooks here (Q-2B-3): stores are checked for changes every 15 minutes
(Shopify stays hourly), a nightly full check also finds deleted products, "Sync now" runs that
full check, and a daily health check reports configuration problems in plain codes.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.commerce.importer import SyncMode, enqueue_reconciliations
from app.providers.base.errors import RetryableError
from sqlalchemy import text

from tests.shopify_sim import ShopifySim, callback_params, sample_catalogue, sample_orders
from tests.shopify_sim import build_provider as build_shopify
from tests.woocommerce_sim import WooSim, approve, build_provider, sample_store

HOST = "shop.example.com"
SHOP = "eve-zone.myshopify.com"


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


def _connect(make_client, sim):
    c = make_client()
    c.email = f"woo-{uuid.uuid4().hex[:6]}@example.com"
    c.signup(c.email)
    c.org = c.create_org("Sync Co")["id"]
    started = c.post(
        f"/organizations/{c.org}/connections/woocommerce/start", {"params": {"store_url": HOST}}
    ).json()["data"]["authorize_url"]
    _, returned = approve(make_client().http, c.http, sim, started)
    c.conn = parse_qs(urlsplit(returned.headers["location"]).query)["connection_id"][0]
    (c.resource,) = c.get(f"/organizations/{c.org}/connections/{c.conn}/resources").json()["data"]
    return c


def _link(make_client, sim):
    c = _connect(make_client, sim)
    assert c.post(f"/organizations/{c.org}/resources/{c.resource['id']}/link").status_code == 201
    (c.store,) = c.get(f"/organizations/{c.org}/stores").json()["data"]
    return c


def _store(c):
    response = c.get(f"/organizations/{c.org}/stores/{c.store['id']}")
    if response.status_code == 401:  # a day passed: the session ended; sign in again
        c.login(c.email)
        c.refresh_csrf()
        response = c.get(f"/organizations/{c.org}/stores/{c.store['id']}")
    return response.json()["data"]


# ------------------------------------------------------------------ how often
def test_woocommerce_is_checked_every_15_minutes_and_shopify_hourly(
    make_client, runtime, sim, clock
):
    shopify = ShopifySim()
    shopify.add_shop(SHOP, catalogue=sample_catalogue(), orders=sample_orders())
    runtime.providers.register(build_shopify(shopify, clock))
    other = make_client()
    other.signup("shopify-side@example.com")
    org = other.create_org("Shopify Co")["id"]
    started = other.post(
        f"/organizations/{org}/connections/shopify/start", {"params": {"shop_domain": SHOP}}
    ).json()["data"]["authorize_url"]
    response = other.http.get(
        "/api/v1/connections/shopify/callback",
        params=callback_params(started),
        follow_redirects=False,
    )
    conn = parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]
    (resource,) = other.get(f"/organizations/{org}/connections/{conn}/resources").json()["data"]
    other.post(f"/organizations/{org}/resources/{resource['id']}/link")
    _link(make_client, sim)

    clock.advance(timedelta(minutes=10))
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 0  # nothing due yet
    clock.advance(timedelta(minutes=6))
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1  # WooCommerce only
    clock.advance(timedelta(minutes=45))
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 2  # both


# ------------------------------------------------------------------ deletions
def test_the_nightly_check_marks_deleted_products_and_variations(
    make_client, runtime, sim, clock, admin_engine
):
    owner = _link(make_client, sim)
    store = sim.stores[HOST]
    store.products = [p for p in store.products if p["id"] != 20]  # Gift Wrap deleted
    store.variations[10] = [v for v in store.variations[10] if v["id"] != 12]  # Large gone
    clock.advance(timedelta(hours=1))
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1  # hourly: never prunes
    assert _rows(admin_engine, "SELECT status FROM products WHERE external_product_id = '20'") == [
        {"status": "unlisted"}
    ]
    clock.advance(timedelta(days=1))
    assert enqueue_reconciliations(runtime, SyncMode.DEEP) == 1
    products = _rows(admin_engine, "SELECT external_product_id, status FROM products ORDER BY 1")
    assert products == [
        {"external_product_id": "10", "status": "active"},
        {"external_product_id": "20", "status": "deleted"},
    ]
    variants = _rows(
        admin_engine, "SELECT external_variant_id, deleted FROM product_variants ORDER BY 1"
    )
    assert variants == [
        {"external_variant_id": "11", "deleted": False},
        {"external_variant_id": "12", "deleted": True},
        {"external_variant_id": "20", "deleted": True},
    ]
    assert len(_rows(admin_engine, "SELECT id FROM order_items")) == 2  # history kept
    _store(owner)  # signs in again after the simulated day
    listed = owner.get(f"/organizations/{owner.org}/stores/{owner.store['id']}/products").json()
    assert [p["title"] for p in listed["data"]["items"]] == ["Nitrile Gloves"]


def test_an_empty_catalogue_answer_deletes_nothing(make_client, runtime, sim, clock, admin_engine):
    _link(make_client, sim)
    sim.stores[HOST].products = []
    clock.advance(timedelta(days=1))
    enqueue_reconciliations(runtime, SyncMode.DEEP)
    statuses = {r["status"] for r in _rows(admin_engine, "SELECT status FROM products")}
    assert "deleted" not in statuses


def test_sync_now_runs_the_full_check(make_client, sim, admin_engine):
    owner = _link(make_client, sim)
    sim.stores[HOST].products = [p for p in sim.stores[HOST].products if p["id"] != 20]
    response = owner.post(f"/organizations/{owner.org}/stores/{owner.store['id']}/resync")
    assert response.status_code == 202
    (row,) = _rows(admin_engine, "SELECT status FROM products WHERE external_product_id = '20'")
    assert row["status"] == "deleted"
    assert _store(owner)["sync"]["last_deep_reconciled_at"] is not None


# ------------------------------------------------------------------ health
def test_a_healthy_store_shows_its_version_address_and_counted_statuses(make_client, sim):
    owner = _link(make_client, sim)
    store = _store(owner)
    assert store["health"]["code"] is None and store["health"]["checked_at"]
    assert (store["platform_version"], store["site_url"]) == ("10.4.1", f"https://{HOST}")
    assert store["counted_statuses"] == ["processing", "on-hold", "completed", "refunded"]


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"cogs_enabled": False}, "cost_of_goods_off"),
        ({"timezone_string": "", "gmt_offset": "5.5"}, "timezone_unknown"),
        ({"version": "8.9.0"}, "woocommerce_too_old"),
    ],
)
def test_configuration_problems_are_found_by_the_daily_check(
    make_client, runtime, sim, clock, change, code
):
    owner = _link(make_client, sim)
    for key, value in change.items():
        setattr(sim.stores[HOST], key, value)
    clock.advance(timedelta(days=1))
    enqueue_reconciliations(runtime, SyncMode.DEEP)
    store = _store(owner)
    assert store["health"]["code"] == code
    assert store["status"] == "active"  # a warning, not a failure


def test_hourly_checks_do_not_repeat_the_health_check(make_client, runtime, sim, clock):
    _link(make_client, sim)
    before = len(sim.calls("/wc/v3/system_status"))
    clock.advance(timedelta(minutes=16))
    enqueue_reconciliations(runtime, SyncMode.RECONCILE)
    after = sim.calls("/wc/v3/system_status")
    # Only the store currency, read once per stage (catalogue, orders) — no health check.
    assert len(after) == before + 2


def test_a_failed_health_check_never_fails_the_sync(make_client, runtime, sim, clock, monkeypatch):
    owner = _link(make_client, sim)
    provider = runtime.providers.get("woocommerce")

    def broken(secrets):
        raise RetryableError("server_error")

    monkeypatch.setattr(provider, "store_health", broken)
    clock.advance(timedelta(days=1))
    enqueue_reconciliations(runtime, SyncMode.DEEP)
    store = _store(owner)
    assert (store["status"], store["sync"]["last_error_code"]) == ("active", None)
    assert store["health"]["code"] == "retryable"


# ------------------------------------------------------------------ access problems
@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        ("revoke", "expired", "key_rejected"),  # "Needs reconnecting"
        ("strip", "error", "auth_header_stripped"),
    ],
)
def test_access_problems_after_import_mark_the_connection(
    make_client, runtime, sim, clock, change, status, code
):
    owner = _link(make_client, sim)
    if change == "revoke":
        sim.stores[HOST].keys.clear()
    else:
        sim.stores[HOST].strips_auth = True
    clock.advance(timedelta(minutes=16))
    enqueue_reconciliations(runtime, SyncMode.RECONCILE)
    connection = owner.get(f"/organizations/{owner.org}/connections/{owner.conn}").json()["data"]
    assert (connection["status"], connection["last_error_code"]) == (status, code)
    store = _store(owner)
    assert store["status"] == "active"  # imported data stays readable
    assert store["sync"]["last_error_code"] == code


def test_a_store_with_an_unknown_time_zone_imports_once_it_is_set(make_client, sim, admin_engine):
    sim.stores[HOST].timezone_string, sim.stores[HOST].gmt_offset = "", "5.5"
    owner = _connect(make_client, sim)
    assert owner.resource["timezone"] is None
    owner.post(f"/organizations/{owner.org}/resources/{owner.resource['id']}/link")
    assert owner.get(f"/organizations/{owner.org}/stores").json()["data"] == []  # waits
    sim.stores[HOST].timezone_string = "Asia/Kolkata"
    assert (
        owner.post(f"/organizations/{owner.org}/connections/{owner.conn}/rediscover").status_code
        == 202
    )
    (store,) = owner.get(f"/organizations/{owner.org}/stores").json()["data"]
    assert (store["timezone"], store["status"]) == ("Asia/Kolkata", "active")
    assert len(_rows(admin_engine, "SELECT id FROM orders")) == 1
