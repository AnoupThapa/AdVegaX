"""The whole Phase 2A journey against the Shopify simulator (task 2A-11, PLAN §16).

One store, start to finish, through the real API, database, job runner and the simulator in
strict-token mode (only the latest access token works; uninstall invalidates every token):

connect from AdVegaX → link → first import → figures → webhook for a new order → a change no
webhook announced is picked up by the hourly check → token expiry and rotation → "Sync now" →
viewer limits → uninstall (data kept, no access) → reinstall from Shopify's install link
(same connection and store, no duplicates) → uninstall again → ``shop/redact`` erases the
store. Throughout: no token appears in any response, the audit log, webhook records or logs.
Acceptance criteria 1, 3, 4 and 5; criterion 2 is covered by the golden finance tests.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.commerce.importer import SyncMode, enqueue_reconciliations
from sqlalchemy import text

from tests.shopify_sim import (
    ShopifySim,
    add_order,
    build_provider,
    callback_params,
    install_params,
    sample_catalogue,
    sample_orders,
    webhook_request,
)

SHOP = "eve-zone.myshopify.com"
TOKEN_MARKERS = ("shpat_", "shprt_", "sim-code")


@pytest.fixture
def sim(runtime, clock):
    s = ShopifySim(strict_tokens=True)
    s.add_shop(SHOP, catalogue=sample_catalogue(), orders=sample_orders())
    runtime.providers.register(build_provider(s, clock))
    return s


class Journey:
    """Keeps every response so the test can prove no token ever left the API."""

    def __init__(self, owner: Any, admin_engine: Any) -> None:
        self.owner = owner
        self.db = admin_engine
        self.bodies: list[str] = []

    def keep(self, response: Any) -> Any:
        self.bodies.append(response.text)
        return response

    def get(self, path: str) -> Any:
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

    def connect(self, http: Any) -> str:
        started = self.post(
            f"/organizations/{self.owner.org}/connections/shopify/start",
            {"params": {"shop_domain": SHOP}},
        ).json()["data"]["authorize_url"]
        response = http.get(
            "/api/v1/connections/shopify/callback",
            params=callback_params(started),
            follow_redirects=False,
        )
        assert response.status_code in (302, 303), response.text
        location = urlsplit(response.headers["location"])
        assert "error" not in parse_qs(location.query), location.query
        return parse_qs(location.query)["connection_id"][0]

    def deliver(self, http: Any, clock: Any, topic: str, payload: dict[str, Any]) -> str:
        headers, body = webhook_request(
            topic,
            payload,
            shop=SHOP,
            webhook_id=str(uuid.uuid4()),
            triggered_at=clock.now().isoformat(),
        )
        response = self.keep(http.post("/api/v1/webhooks/shopify", content=body, headers=headers))
        assert response.status_code == 200, response.text
        return str(response.json()["data"]["status"])


def _day(journey: Journey, store: str, day: str) -> dict[str, Any]:
    data = journey.get(
        f"/organizations/{journey.owner.org}/stores/{store}/metrics/daily?from={day}&to={day}"
    )
    (only,) = data["days"]
    return dict(only)


def test_the_whole_store_journey(make_client, sim, clock, runtime, admin_engine, caplog):
    caplog.set_level(logging.DEBUG)
    owner = make_client()
    owner.signup("journey-owner@example.com")
    owner.org = owner.create_org("Journey Co")["id"]
    j = Journey(owner, admin_engine)
    org = owner.org

    # 1. Connect from AdVegaX; the store is discovered; linking starts the first import.
    conn = j.connect(owner.http)
    (resource,) = j.get(f"/organizations/{org}/connections/{conn}/resources")
    assert (resource["kind"], resource["external_id"]) == ("store", "gid://shopify/Shop/1001")
    assert j.post(f"/organizations/{org}/resources/{resource['id']}/link").status_code == 201
    (store,) = j.get(f"/organizations/{org}/stores")
    assert (store["status"], store["linked"], store["sync"]["running"]) == ("active", True, False)
    assert store["first_import_completed_at"] is not None
    products = j.get(f"/organizations/{org}/stores/{store['id']}/products")["items"]
    assert sorted(p["title"] for p in products) == ["Gift Wrap", "Nitrile Gloves"]
    order_day = _day(j, store["id"], "2026-10-05")
    assert (order_day["net_sales"], order_day["orders_count"]) == ("48.810000", 1)
    assert order_day["cogs"]["availability"] == "unavailable"  # an uncosted line: never partial
    assert j.count("orders") == 1  # the test order is excluded

    # 2. A new order arrives by webhook and today's figures include it within the request.
    oid = add_order(sim.shops[SHOP], processed=clock.now().isoformat())
    assert j.deliver(owner.http, clock, "orders/create", {"admin_graphql_api_id": oid}) == (
        "accepted"
    )
    today = _day(j, store["id"], "2026-10-14")
    assert (today["net_sales"], today["orders_count"]) == ("36.180000", 1)  # 39.80 - 3.62 tax
    assert today["cogs"] == {"value": "14.500000", "availability": "available", "reason": None}

    # 3. An hour later the access token has expired. A product change nobody announced is
    #    picked up by the hourly check, which first rotates both tokens.
    clock.advance(timedelta(hours=1, minutes=5))
    product = next(n for n in sim.shops[SHOP].catalogue if n["id"] == "gid://shopify/Product/1")
    product["title"], product["updatedAt"] = "Nitrile Gloves (box of 100)", clock.now().isoformat()
    tokens_before = len(sim.token_calls)
    assert enqueue_reconciliations(runtime, SyncMode.RECONCILE) == 1
    refresh = parse_qs(sim.token_calls[tokens_before].content.decode())
    assert refresh["grant_type"] == ["refresh_token"]
    titles = [
        p["title"] for p in j.get(f"/organizations/{org}/stores/{store['id']}/products")["items"]
    ]
    assert "Nitrile Gloves (box of 100)" in titles

    # 4. "Sync now" runs the nightly-style check with the rotated token; viewers cannot use it.
    resync = j.post(f"/organizations/{org}/stores/{store['id']}/resync")
    assert resync.status_code == 202, resync.text
    assert j.get(f"/organizations/{org}/stores/{store['id']}")["sync"]["last_deep_reconciled_at"]
    viewer = make_client()
    viewer.signup("journey-viewer@example.com")
    owner.invite_and_join(org, viewer, "journey-viewer@example.com", "viewer")
    assert viewer.get(f"/organizations/{org}/stores/{store['id']}").status_code == 200
    assert viewer.post(f"/organizations/{org}/stores/{store['id']}/resync").status_code == 403

    # 5. The merchant uninstalls the app: access ends at once, the data stays readable.
    sim.uninstall()
    assert j.deliver(owner.http, clock, "app/uninstalled", {"id": 1, "domain": SHOP}) == "accepted"
    assert j.get(f"/organizations/{org}/connections/{conn}")["status"] == "revoked"
    (store_after,) = j.get(f"/organizations/{org}/stores")
    assert store_after["linked"] is False
    assert _day(j, store["id"], "2026-10-14")["net_sales"] == "36.180000"
    busy = j.post(f"/organizations/{org}/stores/{store['id']}/resync")
    assert (busy.status_code, busy.json()["error"]["code"]) == (409, "STORE_NOT_SYNCING")
    assert j.rows("SELECT ciphertext FROM external_connection_credentials")[0]["ciphertext"] is None

    # 6. They install again from Shopify's install link: the browser is sent to choose an
    #    organization; approving reuses the same connection and store — nothing duplicated.
    landing = owner.http.get(
        "/api/v1/connections/shopify/install",
        params=install_params(SHOP, int(clock.now().timestamp())),
        follow_redirects=False,
    )
    assert landing.status_code == 303
    assert urlsplit(landing.headers["location"]).path == "/connect/shopify"
    assert j.connect(owner.http) == conn
    (resource_again,) = j.get(f"/organizations/{org}/connections/{conn}/resources")
    assert resource_again["id"] == resource["id"]
    j.post(f"/organizations/{org}/resources/{resource['id']}/link")
    (store_again,) = j.get(f"/organizations/{org}/stores")
    assert (store_again["id"], store_again["linked"], store_again["status"]) == (
        store["id"],
        True,
        "active",
    )
    assert (j.count("stores"), j.count("products"), j.count("orders")) == (1, 2, 2)
    assert _day(j, store["id"], "2026-10-05")["net_sales"] == "48.810000"

    # 7. Uninstalled again; 48 hours later Shopify asks to erase the store's data.
    sim.uninstall()
    j.deliver(owner.http, clock, "app/uninstalled", {"id": 1, "domain": SHOP})
    clock.advance(timedelta(hours=48))
    j.deliver(owner.http, clock, "shop/redact", {"shop_id": 1, "shop_domain": SHOP})
    for table in ("stores", "products", "orders", "sales_entries", "financial_daily"):
        assert j.count(table) == 0, table
    owner.login("journey-owner@example.com")  # two days idle: the session has ended
    owner.refresh_csrf()
    assert j.get(f"/organizations/{org}/stores") == []
    actions = [r["action"] for r in j.rows("SELECT action FROM audit_logs ORDER BY created_at")]
    for expected in (
        "connection.created",
        "connection.revoked_by_platform",
        "connection.reconnected",
        "store.sync_started",
        "privacy.shop_redacted",
    ):
        assert expected in actions, expected

    # 8. No token or authorization code ever left the API, the audit log, webhook records or logs.
    audit = json.dumps([dict(r) for r in j.rows("SELECT * FROM audit_logs")], default=str)
    events = json.dumps([dict(r) for r in j.rows("SELECT * FROM webhook_events")], default=str)
    for marker in TOKEN_MARKERS:
        for body in j.bodies:
            assert marker not in body
        assert marker not in audit
        assert marker not in events
        # (The test client's own request log shows the simulated redirect from Shopify, which
        # carries the code; only records written while serving requests are checked.)
        served = [
            r.getMessage() for r in caplog.records if "http://testserver" not in r.getMessage()
        ]
        assert all(marker not in line for line in served)
    # Every Admin API call used a token Shopify still accepted (strict simulator).
    assert sim.rejected_tokens == 0
