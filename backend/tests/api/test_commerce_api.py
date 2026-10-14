"""Read API for stores, products and daily figures (task 2A-09, PHASE_02A_PLAN §11).

Uses the imported sample store (Australia/Sydney; one order on 5 Oct, a refund on 8 Oct; three
variants: costed + tracked, uncosted + tracked at 0, costed + untracked).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import text

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


def _connect_and_link(c):
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
    c.post(f"/organizations/{c.org}/resources/{resource['id']}/link")
    return conn, resource["id"]


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup("api-owner@example.com")
    c.org = c.create_org("Api Co")["id"]
    c.conn, c.resource = _connect_and_link(c)
    (store,) = c.get(f"/organizations/{c.org}/stores").json()["data"]
    c.store = store["id"]
    return c


@pytest.fixture
def viewer(make_client, owner):
    c = make_client()
    c.signup("viewer@example.com")
    owner.invite_and_join(owner.org, c, "viewer@example.com", "viewer")
    return c


def _base(c):
    return f"/organizations/{c.org}/stores/{c.store}"


# ------------------------------------------------------------------ stores
def test_store_list_and_detail(owner, clock):
    (store,) = owner.get(f"/organizations/{owner.org}/stores").json()["data"]
    assert store["domain"] == SHOP
    assert (store["currency"], store["currency_minor_units"], store["timezone"]) == (
        "AUD",
        2,
        "Australia/Sydney",
    )
    assert (store["status"], store["linked"], store["connection_status"]) == (
        "active",
        True,
        "active",
    )
    assert store["first_import_completed_at"] is not None
    assert store["sync"]["running"] is False and store["sync"]["mode"] is None
    assert store["sync"]["last_reconciled_at"] is not None
    detail = owner.get(_base(owner)).json()["data"]
    assert detail == store


def test_store_of_another_organization_is_not_found(owner, make_client):
    other = make_client()
    other.signup("other@example.com")
    org = other.create_org("Other Co")["id"]
    assert other.get(f"/organizations/{org}/stores").json()["data"] == []
    for path in ("", "/products", "/metrics/daily", f"/products/{uuid.uuid4()}"):
        response = other.get(f"/organizations/{org}/stores/{owner.store}{path}")
        assert response.status_code == 404, path


# ------------------------------------------------------------------ products
def test_products_with_cost_and_stock_availability(owner):
    page = owner.get(f"{_base(owner)}/products").json()["data"]
    assert page["next_cursor"] is None
    assert [p["title"] for p in page["items"]] == ["Gift Wrap", "Nitrile Gloves"]
    gloves = page["items"][1]
    variants = {v["sku"]: v for v in gloves["variants"]}
    medium, large = variants["NG-M"], variants["NG-L"]
    assert medium["price"] == "19.900000"
    assert medium["inventory"] == {
        "availability": "available",
        "tracked": True,
        "available": 120,
        "synced_at": medium["inventory"]["synced_at"],
    }
    assert medium["cost"]["availability"] == "available"
    assert (medium["cost"]["unit_cost"], medium["cost"]["source"]) == (
        "7.250000",
        "import_snapshot",
    )
    assert large["inventory"]["available"] == 0  # tracked and truly zero
    assert (large["cost"]["availability"], large["cost"]["unit_cost"], large["cost"]["reason"]) == (
        "unavailable",
        None,
        "no_cost_from_platform",
    )
    (wrap,) = page["items"][0]["variants"]
    assert (wrap["inventory"]["availability"], wrap["inventory"]["available"]) == (
        "unavailable",
        None,
    )  # not tracked: never shown as 0


def test_product_paging_search_and_status(owner):
    first = owner.get(f"{_base(owner)}/products?page_size=1").json()["data"]
    assert [p["title"] for p in first["items"]] == ["Gift Wrap"]
    second = owner.get(f"{_base(owner)}/products?page_size=1&cursor={first['next_cursor']}").json()[
        "data"
    ]
    assert [p["title"] for p in second["items"]] == ["Nitrile Gloves"]
    assert second["next_cursor"] is None
    by_sku = owner.get(f"{_base(owner)}/products?q=ng-l").json()["data"]["items"]
    assert [p["title"] for p in by_sku] == ["Nitrile Gloves"]
    wildcard = owner.get(f"{_base(owner)}/products?q=%25").json()["data"]["items"]
    assert wildcard == []  # "%" is a literal character, not "match everything"
    unlisted = owner.get(f"{_base(owner)}/products?status=unlisted").json()["data"]["items"]
    assert [p["title"] for p in unlisted] == ["Gift Wrap"]
    assert owner.get(f"{_base(owner)}/products?status=deleted").json()["data"]["items"] == []


@pytest.mark.parametrize(
    "query", ["status=bogus", "cursor=not-a-cursor", "page_size=0", "page_size=101"]
)
def test_product_query_validation(owner, query):
    response = owner.get(f"{_base(owner)}/products?{query}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_product_detail(owner):
    page = owner.get(f"{_base(owner)}/products").json()["data"]
    product_id = page["items"][1]["id"]
    detail = owner.get(f"{_base(owner)}/products/{product_id}").json()["data"]
    assert detail == page["items"][1]
    assert owner.get(f"{_base(owner)}/products/{uuid.uuid4()}").status_code == 404


def test_deleted_products_are_hidden_by_default(owner, admin_engine):
    with admin_engine.begin() as db:
        db.execute(text("UPDATE products SET status = 'deleted' WHERE title = 'Gift Wrap'"))
    titles = [p["title"] for p in owner.get(f"{_base(owner)}/products").json()["data"]["items"]]
    assert titles == ["Nitrile Gloves"]


# ------------------------------------------------------------------ daily figures
def _metrics(c, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    response = c.get(f"{_base(c)}/metrics/daily?{query}")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_daily_figures_with_availability(owner, clock):
    data = _metrics(owner, **{"from": "2026-10-05", "to": "2026-10-08"})
    assert (data["definition_version"], data["currency"], data["timezone"]) == (
        "finance-v1",
        "AUD",
        "Australia/Sydney",
    )
    days = {d["day"]: d for d in data["days"]}
    assert list(days) == ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]
    order_day = days["2026-10-05"]
    assert (order_day["net_sales"], order_day["total_sales"], order_day["orders_count"]) == (
        "48.810000",
        "63.690000",
        1,
    )
    assert order_day["cogs"] == {
        "value": None,
        "availability": "unavailable",
        "reason": "missing_product_costs",
    }
    assert order_day["cost_coverage"]["value"].startswith("0.774")  # 37.80 / 48.81
    quiet = days["2026-10-06"]  # synced, no activity: real zeros
    assert (quiet["availability"], quiet["net_sales"], quiet["orders_count"]) == (
        "available",
        "0",
        0,
    )
    assert quiet["gross_profit"] == {"value": "0", "availability": "available", "reason": None}
    totals = data["totals"]
    assert (totals["availability"], totals["net_sales"], totals["orders_count"]) == (
        "available",
        "29.910000",  # 48.81 - 18.90
        1,
    )
    assert totals["gross_profit"]["availability"] == "unavailable"
    assert totals["gross_margin"]["reason"] == "missing_product_costs"
    assert totals["shipping_cost"] == {
        "value": None,
        "availability": "unsupported",
        "reason": "not_provided_by_platform",
    }
    assert totals["new_vs_returning"]["availability"] == "unavailable"


def test_days_outside_the_synced_history_are_not_zero(owner, clock):
    store = owner.get(_base(owner)).json()["data"]
    data = owner.get(f"{_base(owner)}/metrics/daily").json()["data"]  # default: last 30 days
    assert len(data["days"]) == 30
    synced_from = date.fromisoformat(data["synced_from"])
    assert synced_from.isoformat() > store["history_from"][:10]
    before = (synced_from - timedelta(days=1)).isoformat()
    tomorrow = (date.fromisoformat(data["to_day"]) + timedelta(days=1)).isoformat()
    partly = _metrics(owner, **{"from": before, "to": synced_from.isoformat()})
    first, second = partly["days"]
    assert (first["availability"], first["net_sales"], first["cogs"]["availability"]) == (
        "not_synchronized",
        None,
        "not_synchronized",
    )
    assert second["availability"] == "available"
    assert partly["totals"]["availability"] == "not_synchronized"
    assert partly["totals"]["net_sales"] is None  # a partial total would understate
    future = _metrics(owner, **{"from": tomorrow, "to": tomorrow})
    assert future["days"][0]["availability"] == "not_synchronized"


def test_store_still_importing_has_no_figures_yet(make_client, sim, runtime):
    c = make_client()
    c.signup("importing-api@example.com")
    c.org = c.create_org("Importing Api Co")["id"]
    original = runtime.enqueue_job
    runtime.enqueue_job = lambda job_id, delay=0: None  # the import never progresses
    try:
        _connect_and_link_no_jobs(c, runtime, original)
    finally:
        runtime.enqueue_job = original
    (store,) = c.get(f"/organizations/{c.org}/stores").json()["data"]
    assert (store["status"], store["sync"]["running"], store["sync"]["mode"]) == (
        "importing",
        True,
        "initial",
    )
    assert store["sync"]["progress"] == 0
    data = c.get(f"/organizations/{c.org}/stores/{store['id']}/metrics/daily").json()["data"]
    assert data["synced_from"] is None
    assert {d["availability"] for d in data["days"]} == {"not_synchronized"}


def _connect_and_link_no_jobs(c, runtime, original):
    runtime.enqueue_job = original  # connecting needs discovery to run
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
    runtime.enqueue_job = lambda job_id, delay=0: None
    c.post(f"/organizations/{c.org}/resources/{resource['id']}/link")


@pytest.mark.parametrize(
    "query", ["from=2026-10-09&to=2026-10-08", "from=2025-01-01&to=2026-10-08", "from=bad"]
)
def test_metrics_range_validation(owner, query):
    response = owner.get(f"{_base(owner)}/metrics/daily?{query}")
    assert response.status_code == 422


# ------------------------------------------------------------------ "Sync now"
def test_resync_runs_a_deep_check_and_is_rate_limited(owner, sim, runtime):
    response = owner.post(f"{_base(owner)}/resync")
    assert response.status_code == 202
    body = response.json()["data"]
    assert (body["store_id"], body["mode"]) == (owner.store, "deep")
    assert "(query:" not in sim.bulk_queries[-2]  # whole catalogue
    runtime.settings = runtime.settings.model_copy(update={"THROTTLE_STORE_RESYNC_PER_HOUR": 1})
    limited = owner.post(f"{_base(owner)}/resync")
    assert limited.status_code == 429


def test_resync_refused_while_a_sync_runs_or_when_unlinked(owner, runtime, admin_engine):
    original = runtime.enqueue_job
    runtime.enqueue_job = lambda job_id, delay=0: None
    try:
        assert owner.post(f"{_base(owner)}/resync").status_code == 202  # starts, never runs
        busy = owner.post(f"{_base(owner)}/resync")
    finally:
        runtime.enqueue_job = original
    assert (busy.status_code, busy.json()["error"]["code"]) == (409, "SYNC_IN_PROGRESS")
    owner.post(f"/organizations/{owner.org}/resources/{owner.resource}/unlink")
    unlinked = owner.post(f"{_base(owner)}/resync")
    assert (unlinked.status_code, unlinked.json()["error"]["code"]) == (409, "STORE_NOT_SYNCING")
    store = owner.get(_base(owner)).json()["data"]
    assert store["linked"] is False


def test_viewers_can_read_but_not_resync(owner, viewer):
    viewer.org, viewer.store = owner.org, owner.store
    assert viewer.get(f"/organizations/{owner.org}/stores").status_code == 200
    assert viewer.get(f"{_base(viewer)}/products").status_code == 200
    assert viewer.get(f"{_base(viewer)}/metrics/daily").status_code == 200
    response = viewer.post(f"{_base(viewer)}/resync")
    assert response.status_code == 403
