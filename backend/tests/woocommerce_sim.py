"""In-process WooCommerce simulator for tests (Phase 2B, PHASE_02B_PLAN §14).

Speaks the documented formats (verified 2026-10-14) behind the real ``SafeHttpClient``: the
public WordPress index, ``wc/v3`` system status (Basic auth), and the merchant's side of
``/wc-auth/v1/authorize`` (generating a key and posting it to AdVegaX). Hosting quirks can be
switched on: a host that strips the ``Authorization`` header, a store that is down, a site
without WooCommerce. Records every request. No network — CI never calls a real store.
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from app.providers.http.client import OutboundPolicy, SafeHttpClient
from app.providers.woocommerce.provider import WooCommerceProvider

PUBLIC_IP = "93.184.216.34"
POLICY = OutboundPolicy(
    connect_timeout=1, read_timeout=1, max_response_bytes=1_000_000, max_redirects=0
)


@dataclass
class WooStore:
    host: str
    path: str = ""
    name: str = "Mediflex Test"
    currency: str = "AUD"
    timezone_string: str = "Australia/Sydney"
    gmt_offset: str = "10"
    version: str = "10.4.1"
    woocommerce: bool = True
    keys: dict[str, tuple[str, str]] = field(default_factory=dict)  # ck → (cs, permissions)
    strips_auth: bool = False  # the web host removes the Authorization header
    status: int = 200  # force an error status for every request (e.g. 503)
    data: dict[str, Any] = field(default_factory=dict)  # route → JSON (fixed answers)
    # Collections served with WordPress paging and filters (2B-05).
    products: list[dict[str, Any]] = field(default_factory=list)
    variations: dict[int, list[dict[str, Any]]] = field(default_factory=dict)  # parent → list
    orders: list[dict[str, Any]] = field(default_factory=list)
    refunds: list[dict[str, Any]] = field(default_factory=list)
    max_per_page: int = 100
    cogs_enabled: bool = True  # off: WooCommerce sends no cost_of_goods_sold fields at all


@dataclass
class WooSim:
    stores: dict[str, WooStore] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    issued: int = 0

    def add_store(self, host: str, **kw: Any) -> WooStore:
        store = WooStore(host, **kw)
        self.stores[host] = store
        return store

    def issue_key(self, host: str, permissions: str = "read") -> tuple[str, str]:
        self.issued += 1
        ck = f"ck_{secrets.token_hex(20)}"
        cs = f"cs_{secrets.token_hex(20)}"
        self.stores[host].keys[ck] = (cs, permissions)
        return ck, cs

    def calls(self, part: str) -> list[httpx.Request]:
        return [r for r in self.requests if part in r.url.path]

    # -- transport ---------------------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        store = self.stores.get(request.headers["host"])
        if store is None:
            return httpx.Response(404, text="no such site")
        if store.status != 200:
            return httpx.Response(store.status, json={"code": "down"})
        path = request.url.path
        base = f"{store.path}/wp-json"
        if not path.startswith(base):
            return httpx.Response(404, text="<html>not found</html>")
        route = path[len(base) :] or "/"
        if route == "/":
            return self._index(store)
        if not store.woocommerce or not route.startswith("/wc/v3/"):
            return _error(404, "rest_no_route")
        auth = None if store.strips_auth else request.headers.get("authorization")
        if auth is None:
            return _error(401, "woocommerce_rest_cannot_view")
        if not self._authorized(store, auth):
            return _error(401, "woocommerce_rest_authentication_error")
        if route == "/wc/v3/system_status":
            return httpx.Response(
                200,
                json={
                    "environment": {
                        "version": store.version,
                        "wp_version": "6.8",
                        "site_url": f"https://{store.host}{store.path}",
                        "default_timezone": "UTC",
                    },
                    "settings": {"currency": store.currency, "number_of_decimals": 2},
                    "security": {"secure_connection": True},
                },
            )
        sub = route[len("/wc/v3") :]
        if sub in store.data:
            return httpx.Response(200, json=store.data[sub])
        params = dict(request.url.params)
        if sub == "/products":
            items = store.products
            if "type" in params:
                items = [p for p in items if p.get("type") == params["type"]]
            return self._collection(store, items, params, modified="date_modified_gmt")
        if sub.startswith("/products/") and sub.endswith("/variations"):
            parent = int(sub.split("/")[2])
            return self._collection(
                store, store.variations.get(parent, []), params, modified="date_modified_gmt"
            )
        if sub == "/orders":
            return self._collection(
                store,
                store.orders,
                params,
                modified="date_modified_gmt",
                created="date_created_gmt",
            )
        if sub == "/refunds":
            return self._collection(store, store.refunds, params, created="date_created_gmt")
        return _error(404, "rest_no_route")

    def _collection(
        self,
        store: WooStore,
        items: list[dict[str, Any]],
        params: dict[str, str],
        *,
        modified: str | None = None,
        created: str | None = None,
    ) -> httpx.Response:
        """WordPress paging (``page``/``per_page``, ``X-WP-Total(Pages)``) and the date filters
        ``after`` / ``modified_after`` (ISO strings compare correctly)."""
        if params.get("orderby", "id") != "id" or params.get("order", "asc") != "asc":
            return _error(400, "rest_invalid_param")
        per_page = int(params.get("per_page", "10"))
        if not 1 <= per_page <= store.max_per_page:
            return _error(400, "rest_invalid_param")
        page = int(params.get("page", "1"))
        selected = sorted(items, key=lambda i: i["id"])
        if "after" in params and created:
            selected = [i for i in selected if i.get(created, "") > params["after"]]
        if "modified_after" in params and modified:
            selected = [i for i in selected if i.get(modified, "") > params["modified_after"]]
        total = len(selected)
        pages = max(1, -(-total // per_page))
        chunk = selected[(page - 1) * per_page : page * per_page]
        if not store.cogs_enabled:
            chunk = [_without_costs(i) for i in chunk]
        fields = params.get("_fields")
        if fields:  # the store honours _fields (to confirm live, Step 0 item 3)
            wanted = set(fields.split(","))
            chunk = [{k: v for k, v in i.items() if k in wanted} for i in chunk]
        return httpx.Response(
            200, json=chunk, headers={"X-WP-Total": str(total), "X-WP-TotalPages": str(pages)}
        )

    def _index(self, store: WooStore) -> httpx.Response:
        namespaces = ["wp/v2", "wc/store/v1"] + (
            ["wc/v3", "wc-auth/v1"] if store.woocommerce else []
        )
        return httpx.Response(
            200,
            json={
                "name": store.name,
                "url": f"https://{store.host}{store.path}",
                "timezone_string": store.timezone_string,
                "gmt_offset": store.gmt_offset,
                "namespaces": namespaces,
            },
        )

    @staticmethod
    def _authorized(store: WooStore, header: str) -> bool:
        if not header.startswith("Basic "):
            return False
        try:
            ck, _, cs = base64.b64decode(header[6:]).decode().partition(":")
        except ValueError:
            return False
        known = store.keys.get(ck)
        return known is not None and known[0] == cs

    def http_factory(self) -> SafeHttpClient:
        return SafeHttpClient(
            POLICY,
            resolver=lambda host, port: [PUBLIC_IP],
            transport=httpx.MockTransport(self.handler),
        )


def _without_costs(item: dict[str, Any]) -> dict[str, Any]:
    item = {k: v for k, v in item.items() if k != "cost_of_goods_sold"}
    if isinstance(item.get("line_items"), list):
        item["line_items"] = [
            {k: v for k, v in line.items() if k != "cost_of_goods_sold"}
            for line in item["line_items"]
        ]
    return item


def _error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"code": code, "message": "x", "data": {"status": status}})


def build_provider(sim: WooSim, *, gentle: bool = False, **kw: Any) -> WooCommerceProvider:
    """The provider against the simulator. The test clock does not move by itself, so the
    per-store request limiter would never refill: tests use a wide limit unless ``gentle``."""
    provider = WooCommerceProvider(http_factory=sim.http_factory, **kw)
    if not gentle:
        provider.rate_limit = (1000.0, 10_000)  # type: ignore[misc]
    return provider


@dataclass(frozen=True)
class Approval:
    user_id: str
    callback_path: str
    return_path: str
    delivery: httpx.Response | None
    key: tuple[str, str] | None


def approve(
    api: Any,
    browser: Any,
    sim: WooSim,
    authorize_url: str,
    *,
    permissions: str = "read",
    deliver: bool = True,
    success: bool = True,
    key_from: str | None = None,
) -> tuple[Approval, httpx.Response]:
    """Play the merchant on ``/wc-auth/v1/authorize``: the store generates a key, posts it to
    AdVegaX server to server (``api``: a client without the person's session), then sends the
    person's ``browser`` back to ``return_url``. Returns the approval and the browser's
    response (a redirect into the web app)."""
    parts = urlsplit(authorize_url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.path.endswith("/wc-auth/v1/authorize"), parts.path
    assert query["scope"] == "read"
    callback = urlsplit(query["callback_url"])
    back = urlsplit(query["return_url"])
    delivery, key = None, None
    if success and deliver:
        key = sim.issue_key(key_from or parts.hostname or "", permissions)
        delivery = api.post(
            callback.path,
            json={
                "key_id": sim.issued,
                "user_id": query["user_id"],
                "consumer_key": key[0],
                "consumer_secret": key[1],
                "key_permissions": permissions,
            },
        )
    returned = browser.get(
        back.path,
        params={"success": "1" if success else "0", "user_id": query["user_id"]},
        follow_redirects=False,
    )
    return Approval(query["user_id"], callback.path, back.path, delivery, key), returned


# ---------------------------------------------------------------- sample store (2B-05)
CUSTOMER = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@example.com",
    "phone": "+61 400 000 000",
    "address_1": "1 Secret Street",
}


def sample_store(store: WooStore) -> WooStore:
    """The same store as the Shopify sample (tests/shopify_sim.py), in WooCommerce's format:
    gloves (Medium: tracked 120, cost 7.25; Large: tracked 0, no cost) and gift wrap (not
    tracked, cost 1.10, private); one order on 5 Oct (2 x Medium with a 2.00 discount, a
    custom engraving line without product or cost, shipping) and a refund of one Medium
    on 8 Oct. Customer details are included on purpose: they must never be stored."""
    store.products = [
        {
            "id": 10,
            "name": "Nitrile Gloves",
            "slug": "nitrile-gloves",
            "type": "variable",
            "status": "publish",
            "sku": "",
            "price": "19.90",
            "manage_stock": False,
            "stock_quantity": None,
            "date_modified_gmt": "2026-10-01T00:00:00",
            "categories": [{"id": 3, "name": "Gloves"}],
            "cost_of_goods_sold": {"values": [], "total_value": 0},  # on, nothing defined
        },
        {
            "id": 20,
            "name": "Gift Wrap",
            "slug": "gift-wrap",
            "type": "simple",
            "status": "private",
            "sku": "",
            "price": "5.00",
            "manage_stock": False,
            "stock_quantity": None,
            "date_modified_gmt": "2026-10-02T00:00:00",
            "categories": [],
            "cost_of_goods_sold": {"values": [{"defined_value": 1.1}], "total_value": 1.1},
        },
    ]
    store.variations = {
        10: [
            {
                "id": 11,
                "parent_id": 10,
                "sku": "NG-M",
                "price": "19.90",
                "manage_stock": True,
                "stock_quantity": 120,
                "date_modified_gmt": "2026-10-01T00:00:00",
                "attributes": [{"name": "Size", "option": "Medium"}],
                "cost_of_goods_sold": {"values": [{"defined_value": 7.25}], "total_value": 7.25},
            },
            {
                "id": 12,
                "parent_id": 10,
                "sku": "NG-L",
                "price": "21.90",
                "manage_stock": True,
                "stock_quantity": 0,
                "date_modified_gmt": "2026-10-01T00:00:00",
                "attributes": [{"name": "Size", "option": "Large"}],
                "cost_of_goods_sold": {"values": [], "total_value": 0},
            },
        ]
    }
    store.orders = [
        {
            "id": 500,
            "number": "1001",
            "status": "completed",
            "currency": "AUD",
            "date_created_gmt": "2026-10-05T01:30:00",
            "date_modified_gmt": "2026-10-08T03:00:00",
            "discount_total": "2.00",
            "shipping_total": "9.08",
            "total": "63.69",
            "total_tax": "5.80",
            "customer_id": 7,
            "billing": dict(CUSTOMER),
            "shipping": dict(CUSTOMER),
            "customer_note": "Leave at the back door",
            "line_items": [
                {
                    "id": 601,
                    "name": "Nitrile Gloves - Medium",
                    "product_id": 10,
                    "variation_id": 11,
                    "quantity": 2,
                    "subtotal": "39.80",
                    "subtotal_tax": "3.96",
                    "total": "37.80",
                    "total_tax": "3.78",
                    "sku": "NG-M",
                    "price": 18.9,
                    "cost_of_goods_sold": {"value": 14.5},
                },
                {
                    "id": 602,
                    "name": "Custom engraving",
                    "product_id": 0,
                    "variation_id": 0,
                    "quantity": 1,
                    "subtotal": "11.01",
                    "subtotal_tax": "1.10",
                    "total": "11.01",
                    "total_tax": "1.10",
                    "sku": "",
                    "price": 11.01,
                },
            ],
            "shipping_lines": [
                {"id": 603, "method_title": "Flat rate", "total": "9.08", "total_tax": "0.92"}
            ],
            "fee_lines": [],
            "refunds": [{"id": 900, "reason": "", "total": "-20.79"}],
        }
    ]
    store.refunds = [
        {
            "id": 900,
            "parent_id": 500,
            "date_created_gmt": "2026-10-08T03:00:00",
            "amount": "20.79",
            "reason": "Damaged",
            "line_items": [
                {
                    "id": 901,
                    "name": "Nitrile Gloves - Medium",
                    "product_id": 10,
                    "variation_id": 11,
                    "quantity": -1,
                    "subtotal": "-19.90",
                    "total": "-18.90",
                    "total_tax": "-1.89",
                    "meta_data": [{"key": "_refunded_item_id", "value": "601"}],
                    "cost_of_goods_sold": {"value": -7.25},
                }
            ],
            "shipping_lines": [],
            "fee_lines": [],
        }
    ]
    return store
