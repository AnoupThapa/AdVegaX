"""The whole Phase 2B journey against the WooCommerce simulator (task 2B-09, PLAN §14, §16).

One store, start to finish, through the real API, database, job runner and simulator:

connect (the store's own approval page; the key arrives server to server) → link → first
import → figures equal to the Shopify sample → a new order and a product change picked up by
the 15-minute check → a refund on a later check → a pending order that gets paid → the
merchant revokes the key ("Needs reconnecting", data kept) → reconnect (same connection and
store, nothing duplicated, updates resume) → disconnect (key deleted, no call to the store,
data kept). Throughout: no key, secret or customer detail appears in any response, the audit
log, the database or the logs. Acceptance criteria 1, 3 and 5; criterion 2 is the parity tests.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.commerce.importer import SyncMode, enqueue_reconciliations
from sqlalchemy import text

from tests.woocommerce_sim import CUSTOMER, WooSim, approve, build_provider, sample_store

HOST = "shop.example.com"
CUSTOMER_MARKERS = tuple(str(v) for v in CUSTOMER.values())


@pytest.fixture
def sim(runtime, settings):
    s = WooSim()
    sample_store(s.add_store(HOST))
    runtime.providers.register(
        build_provider(s, reconcile_interval=settings.WOOCOMMERCE_RECONCILE_INTERVAL)
    )
    return s


class Journey:
    """Keeps every response so the test can prove no key ever left the API."""

    def __init__(self, owner: Any, make_client: Any, sim: WooSim, admin_engine: Any) -> None:
        self.owner, self.make_client, self.sim, self.db = owner, make_client, sim, admin_engine
        self.bodies: list[str] = []
        self.keys: list[tuple[str, str]] = []

    def keep(self, response: Any) -> Any:
        self.bodies.append(response.text)
        return response

    def get(self, path: str) -> Any:
        response = self.keep(self.owner.get(path))
        if response.status_code == 401:  # a simulated day passed: the session ended
            self.owner.login(self.owner.email)
            self.owner.refresh_csrf()
            response = self.keep(self.owner.get(path))
        assert response.status_code == 200, (path, response.text)
        return response.json()["data"]

    def post(self, path: str, body: Any = None) -> Any:
        return self.keep(self.owner.post(path, body))

    def rows(self, sql: str, **params: Any) -> list[Any]:
        with self.db.begin() as db:
            return list(db.execute(text(sql), params).mappings().all())

    def count(self, table: str) -> int:
        return int(self.rows(f"SELECT count(*) AS n FROM {table}")[0]["n"])

    def connect(self) -> str:
        started = self.post(
            f"/organizations/{self.owner.org}/connections/woocommerce/start",
            {"params": {"store_url": f"https://{HOST}/wp-admin/"}},
        ).json()["data"]["authorize_url"]
        approval, returned = approve(self.make_client().http, self.owner.http, self.sim, started)
        assert approval.delivery is not None and approval.key is not None
        self.keep(approval.delivery)
        self.keys.append(approval.key)
        query = parse_qs(urlsplit(returned.headers["location"]).query)
        assert query.get("status") == ["connected"], query
        return query["connection_id"][0]


def _day(j: Journey, store: str, day: str) -> dict[str, Any]:
    data = j.get(f"/organizations/{j.owner.org}/stores/{store}/metrics/daily?from={day}&to={day}")
    (only,) = data["days"]
    return dict(only)


def _stamp(moment: Any) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def _new_order(store: Any, order_id: int, moment: Any, **changes: Any) -> dict[str, Any]:
    order = copy.deepcopy(store.orders[0])
    order.update(
        id=order_id,
        number=str(order_id),
        refunds=[],
        date_created_gmt=_stamp(moment),
        date_modified_gmt=_stamp(moment),
        **changes,
    )
    for offset, line in enumerate([*order["line_items"], *order["shipping_lines"]]):
        line["id"] = order_id * 10 + offset
    store.orders.append(order)
    return order


def test_the_whole_woocommerce_store_journey(
    make_client, sim, clock, runtime, admin_engine, caplog
):
    caplog.set_level(logging.DEBUG)
    owner = make_client()
    owner.email = "woo-journey@example.com"
    owner.signup(owner.email)
    owner.org = owner.create_org("Woo Journey Co")["id"]
    j = Journey(owner, make_client, sim, admin_engine)
    org = owner.org
    store_data = sim.stores[HOST]

    # 1. Connect: the address is tidied, the store's approval page delivers a read-only key.
    conn = j.connect()
    (resource,) = j.get(f"/organizations/{org}/connections/{conn}/resources")
    assert (resource["kind"], resource["timezone"]) == ("store", "Australia/Sydney")
    assert j.post(f"/organizations/{org}/resources/{resource['id']}/link").status_code == 201
    (store,) = j.get(f"/organizations/{org}/stores")
    sid = store["id"]
    assert (store["provider"], store["status"], store["site_url"]) == (
        "woocommerce",
        "active",
        f"https://{HOST}",
    )
    assert store["health"]["code"] is None
    assert store["counted_statuses"] == ["processing", "on-hold", "completed", "refunded"]
    products = j.get(f"/organizations/{org}/stores/{sid}/products")["items"]
    assert sorted(p["title"] for p in products) == ["Gift Wrap", "Nitrile Gloves"]
    sale = _day(j, sid, "2026-10-05")  # the Shopify sample's golden values
    assert (sale["net_sales"], sale["total_sales"], sale["orders_count"]) == (
        "48.810000",
        "63.690000",
        1,
    )
    assert sale["cogs"]["availability"] == "unavailable"  # the engraving line has no cost
    assert _day(j, sid, "2026-10-08")["sales_reversals"] == "18.900000"

    # 2. 16 minutes later: a new order and a renamed product, found by the 15-minute check.
    clock.advance(timedelta(minutes=16))
    _new_order(store_data, 700, clock.now() - timedelta(minutes=2))
    product = store_data.products[0]
    product["name"] = "Nitrile Gloves (box of 100)"
    product["date_modified_gmt"] = _stamp(clock.now() - timedelta(minutes=1))
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1
    today = _day(j, sid, "2026-10-14")
    assert (today["total_sales"], today["orders_count"]) == ("63.690000", 1)
    titles = [p["title"] for p in j.get(f"/organizations/{org}/stores/{sid}/products")["items"]]
    assert "Nitrile Gloves (box of 100)" in titles

    # 3. A refund of one item of the new order, on the next check.
    clock.advance(timedelta(minutes=16))
    refund = copy.deepcopy(store_data.refunds[0])
    refund.update(id=960, parent_id=700, date_created_gmt=_stamp(clock.now()))
    refund["line_items"][0].update(
        id=961, meta_data=[{"key": "_refunded_item_id", "value": "7000"}]
    )
    store_data.refunds.append(refund)
    order = store_data.orders[-1]
    order["refunds"] = [{"id": 960, "reason": "", "total": "-20.79"}]
    order["date_modified_gmt"] = _stamp(clock.now())
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1
    today = _day(j, sid, "2026-10-14")
    assert (today["total_sales"], today["sales_reversals"]) == ("42.900000", "18.900000")

    # 4. A pending order is not counted until it is paid.
    clock.advance(timedelta(minutes=16))
    pending = _new_order(store_data, 701, clock.now() - timedelta(minutes=1), status="pending")
    enqueue_reconciliations(runtime, SyncMode.RECONCILE)
    assert _day(j, sid, "2026-10-14")["orders_count"] == 1
    clock.advance(timedelta(minutes=16))
    pending.update(status="processing", date_modified_gmt=_stamp(clock.now()))
    enqueue_reconciliations(runtime, SyncMode.RECONCILE)
    assert _day(j, sid, "2026-10-14")["orders_count"] == 2

    # 5. The merchant revokes the key: "Needs reconnecting"; the imported data stays readable.
    store_data.keys.clear()
    clock.advance(timedelta(minutes=16))
    enqueue_reconciliations(runtime, SyncMode.RECONCILE)
    connection = j.get(f"/organizations/{org}/connections/{conn}")
    assert (connection["status"], connection["last_error_code"]) == ("expired", "key_rejected")
    assert _day(j, sid, "2026-10-05")["net_sales"] == "48.810000"
    clock.advance(timedelta(minutes=16))
    before = len(sim.requests)
    enqueue_reconciliations(runtime, SyncMode.RECONCILE)
    assert len(sim.requests) == before  # no more calls with a refused key

    # 6. Reconnect: the same connection and store; nothing duplicated; updates resume.
    assert j.connect() == conn
    assert j.get(f"/organizations/{org}/connections/{conn}")["status"] == "active"
    (kept,) = j.get(f"/organizations/{org}/connections/{conn}/resources")
    assert (kept["id"], kept["linked"]) == (resource["id"], True)  # the link survived
    (again,) = j.get(f"/organizations/{org}/stores")
    assert (again["id"], again["linked"]) == (sid, True)
    assert (j.count("stores"), j.count("orders")) == (1, 3)
    clock.advance(timedelta(minutes=16))
    _new_order(store_data, 702, clock.now() - timedelta(minutes=1))
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1
    assert _day(j, sid, "2026-10-14")["orders_count"] == 3

    # 7. The nightly check and the daily health check still run on the new key.
    clock.advance(timedelta(days=1))
    store_data.cogs_enabled = False
    enqueue_reconciliations(runtime, SyncMode.DEEP)
    assert j.get(f"/organizations/{org}/stores/{sid}")["health"]["code"] == "cost_of_goods_off"

    # 8. Disconnect: the key is deleted, the store is not called, the data is kept.
    before = len(sim.requests)
    disconnected = j.post(f"/organizations/{org}/connections/{conn}/disconnect")
    assert disconnected.json()["data"]["status"] == "revoked"
    assert len(sim.requests) == before
    assert {
        r["ciphertext"] for r in j.rows("SELECT ciphertext FROM external_connection_credentials")
    } == {None}
    (after,) = j.get(f"/organizations/{org}/stores")
    assert after["linked"] is False
    assert _day(j, sid, "2026-10-05")["net_sales"] == "48.810000"
    busy = j.post(f"/organizations/{org}/stores/{sid}/resync")
    assert (busy.status_code, busy.json()["error"]["code"]) == (409, "STORE_NOT_SYNCING")
    actions = [r["action"] for r in j.rows("SELECT action FROM audit_logs ORDER BY created_at")]
    for expected in ("connection.created", "connection.reconnected", "store.import_completed"):
        assert expected in actions, expected

    # 9. No key, secret or customer detail ever left the API or reached the audit log, the
    #    stored orders or the logs (the test client's own request lines are not checked).
    audit = json.dumps([dict(r) for r in j.rows("SELECT * FROM audit_logs")], default=str)
    orders = json.dumps([dict(r) for r in j.rows("SELECT * FROM orders")], default=str)
    served = [r.getMessage() for r in caplog.records if "http://testserver" not in r.getMessage()]
    secrets = [part for key in j.keys for part in key]
    for marker in (*secrets, *CUSTOMER_MARKERS):
        assert all(marker not in body for body in j.bodies), marker
        assert marker not in audit and marker not in orders, marker
        assert all(marker not in line for line in served), marker
