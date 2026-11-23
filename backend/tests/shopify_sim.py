"""In-process Shopify simulator for tests (PHASE_02A_PLAN §12, option C).

Speaks the documented formats (verified 2026-10-13) for the OAuth token endpoint and the GraphQL
Admin API, behind the real ``SafeHttpClient`` (a fake resolver returns a public address; the
transport is ``httpx.MockTransport``). It records every request so tests can prove, for example,
that no token exchange happened. No network is used — CI never calls Shopify.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from app.core.clock import Clock
from app.providers.http.client import OutboundPolicy, SafeHttpClient
from app.providers.shopify.config import ShopifyApp
from app.providers.shopify.provider import ShopifyProvider
from app.providers.shopify.signatures import sign_body, sign_query

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret-0123456789"
API_VERSION = "2026-10"
SCOPES = ("read_products", "read_inventory", "read_orders")
PUBLIC_IP = "23.227.38.65"
POLICY = OutboundPolicy(
    connect_timeout=1, read_timeout=1, max_response_bytes=1_000_000, max_redirects=0
)


@dataclass
class Shop:
    domain: str
    name: str = "Eve Zone Test"
    currency: str = "AUD"
    timezone: str = "Australia/Sydney"
    gid: str = "gid://shopify/Shop/1001"
    # Bulk-export contents (JSONL nodes, in Shopify's documented format).
    catalogue: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)


BULK_HOST = "storage.googleapis.com"


@dataclass
class ShopifySim:
    shops: dict[str, Shop] = field(default_factory=dict)
    granted_scope: str = ",".join(SCOPES)
    token_status: int = 200
    graphql_status: int = 200
    graphql_errors: list[dict[str, Any]] | None = None
    requests: list[httpx.Request] = field(default_factory=list)
    issued: int = 0
    # Bulk operations: polls answered RUNNING before COMPLETED; final status; failures.
    bulk_polls_running: int = 0
    bulk_final_status: str = "COMPLETED"
    bulk_error_code: str | None = None
    bulk_user_errors: bool = False
    download_status: int = 200
    download_failures: int = 0  # the next N downloads answer 403 (expired signed link)
    bulk_queries: list[str] = field(default_factory=list)
    # Single-object fetches (2A-07): max nodes per nested list before hasNextPage is true.
    page_limit: int = 250
    fetches: list[tuple[str, str]] = field(default_factory=list)
    throttle_next: int = 0  # answer the next N GraphQL calls with THROTTLED
    operations: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Strict tokens (2A-11): only the most recently issued access token works, as after a
    # rotation at Shopify; ``uninstall()`` invalidates every token.
    strict_tokens: bool = False
    installed: bool = True
    rejected_tokens: int = 0

    def add_shop(self, domain: str, **kw: Any) -> Shop:
        shop = Shop(domain, **kw)
        self.shops[domain] = shop
        return shop

    # -- recorded traffic -------------------------------------------------------------
    def calls(self, path_part: str) -> list[httpx.Request]:
        return [r for r in self.requests if path_part in r.url.path]

    @property
    def token_calls(self) -> list[httpx.Request]:
        return self.calls("/admin/oauth/access_token")

    # -- transport --------------------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.headers["host"]
        if host == BULK_HOST:
            return self._download(request)
        if host not in self.shops:
            return httpx.Response(404, json={"errors": "Not Found"})
        if request.url.path == "/admin/oauth/access_token":
            return self._token(request)
        if request.url.path == f"/admin/api/{API_VERSION}/graphql.json":
            return self._graphql(request, self.shops[host])
        return httpx.Response(404)

    def _token(self, request: httpx.Request) -> httpx.Response:
        if self.token_status != 200:
            return httpx.Response(self.token_status, json={"error": "invalid_request"})
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if form.get("client_secret") != CLIENT_SECRET:
            return httpx.Response(400, json={"error": "invalid_request"})
        if form.get("grant_type") == "refresh_token":
            # Rotation: only the most recently issued refresh token is accepted.
            current = f"shprt_sim_refresh_{self.issued}"
            if form.get("refresh_token") != current or not self.installed:
                return httpx.Response(400, json={"error": "invalid_grant"})
            form["expiring"] = "1"
        elif not form.get("code"):
            return httpx.Response(400, json={"error": "invalid_request"})
        else:
            self.installed = True  # a new authorization code means the app is installed again
        self.issued += 1
        body: dict[str, Any] = {
            "access_token": f"shpat_sim_access_{self.issued}",
            "scope": self.granted_scope,
        }
        if form.get("expiring") == "1":
            body.update(
                expires_in=3600,
                refresh_token=f"shprt_sim_refresh_{self.issued}",
                refresh_token_expires_in=7_776_000,
            )
        return httpx.Response(200, json=body)

    def uninstall(self) -> None:
        """The merchant removed the app: Shopify invalidates its tokens."""
        self.installed = False

    def _token_ok(self, token: str) -> bool:
        if not token.startswith("shpat_sim_"):
            return False
        if self.strict_tokens:
            return self.installed and token == f"shpat_sim_access_{self.issued}"
        return True

    def _graphql(self, request: httpx.Request, shop: Shop) -> httpx.Response:
        if not self._token_ok(request.headers.get("x-shopify-access-token", "")):
            self.rejected_tokens += 1
            return httpx.Response(401, json={"errors": "[API] Invalid API key or access token"})
        if self.graphql_status != 200:
            headers = {"Retry-After": "2.0"} if self.graphql_status == 429 else {}
            return httpx.Response(self.graphql_status, headers=headers, json={"errors": "x"})
        if self.graphql_errors:
            return httpx.Response(200, json={"errors": self.graphql_errors})
        payload = json.loads(request.content)
        query = payload["query"]
        if self.throttle_next > 0:
            self.throttle_next -= 1
            return httpx.Response(
                200,
                json={
                    "errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}],
                    "extensions": {
                        "cost": {
                            "requestedQueryCost": 502,
                            "actualQueryCost": None,
                            "throttleStatus": {
                                "maximumAvailable": 2000.0,
                                "currentlyAvailable": 2,
                                "restoreRate": 100.0,
                            },
                        }
                    },
                },
            )
        if "query AdVegaXProduct(" in query:
            return self._fetch(shop, "product", payload["variables"]["id"])
        if "query AdVegaXOrder(" in query:
            return self._fetch(shop, "order", payload["variables"]["id"])
        if "bulkOperationRunQuery" in query:
            return self._bulk_run(shop, payload["variables"]["query"])
        if "bulkOperation(id:" in query:
            return self._bulk_state(payload["variables"]["id"])
        if "shop {" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "shop": {
                            "id": shop.gid,
                            "name": shop.name,
                            "currencyCode": shop.currency,
                            "ianaTimezone": shop.timezone,
                            "myshopifyDomain": shop.domain,
                        }
                    }
                },
            )
        return httpx.Response(200, json={"data": {}})

    # -- single-object fetches (2A-07) ---------------------------------------------------
    def _connection(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        page = nodes[: self.page_limit]
        return {
            "pageInfo": {"hasNextPage": len(nodes) > self.page_limit},
            "edges": [{"node": strip(n)} for n in page],
        }

    def _fetch(self, shop: Shop, kind: str, object_id: str) -> httpx.Response:
        self.fetches.append((kind, object_id))
        source = shop.catalogue if kind == "product" else shop.orders
        node = next((n for n in source if n.get("id") == object_id and "__parentId" not in n), None)
        if node is None:
            return httpx.Response(200, json={"data": {kind: None}})
        children = [n for n in source if n.get("__parentId") == object_id]
        result = strip(node)
        if kind == "product":
            result["variants"] = self._connection(children)
        else:
            lines = [c for c in children if "originalUnitPriceSet" in c]
            agreements = []
            for agreement in (c for c in children if "happenedAt" in c):
                sales = [n for n in source if n.get("__parentId") == agreement["id"]]
                agreements.append({**strip(agreement), "sales": self._connection(sales)})
            result["lineItems"] = self._connection(lines)
            result["agreements"] = {
                "pageInfo": {"hasNextPage": len(agreements) > self.page_limit},
                "edges": [{"node": a} for a in agreements[: self.page_limit]],
            }
        return httpx.Response(200, json={"data": {kind: result}})

    # -- bulk operations ------------------------------------------------------------------
    def _bulk_run(self, shop: Shop, inner: str) -> httpx.Response:
        self.bulk_queries.append(inner)
        if self.bulk_user_errors:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "bulkOperationRunQuery": {
                            "bulkOperation": None,
                            "userErrors": [{"field": ["query"], "message": "Invalid query"}],
                        }
                    }
                },
            )
        number = len(self.operations) + 1
        op_id = f"gid://shopify/BulkOperation/{number}"
        nodes = shop.catalogue if "products" in inner.split("{", 2)[1] else shop.orders
        self.operations[op_id] = {"polls": 0, "nodes": nodes, "file": f"/sim/bulk-{number}.jsonl"}
        return httpx.Response(
            200,
            json={
                "data": {
                    "bulkOperationRunQuery": {
                        "bulkOperation": {"id": op_id, "status": "CREATED"},
                        "userErrors": [],
                    }
                }
            },
        )

    def _bulk_state(self, op_id: str) -> httpx.Response:
        op = self.operations.get(op_id)
        if op is None:
            return httpx.Response(200, json={"data": {"bulkOperation": None}})
        op["polls"] += 1
        running = op["polls"] <= self.bulk_polls_running
        status = "RUNNING" if running else self.bulk_final_status
        done = status == "COMPLETED"
        url = (
            f"https://{BULK_HOST}{op['file']}?X-Goog-Signature=sim"
            if done and op["nodes"]
            else None
        )
        return httpx.Response(
            200,
            json={
                "data": {
                    "bulkOperation": {
                        "id": op_id,
                        "status": status,
                        "errorCode": None if done or running else self.bulk_error_code,
                        "objectCount": str(len(op["nodes"])),
                        "url": url,
                        "partialDataUrl": None,
                    }
                }
            },
        )

    def _download(self, request: httpx.Request) -> httpx.Response:
        if self.download_failures > 0:
            self.download_failures -= 1
            return httpx.Response(403, text="<Error>ExpiredToken</Error>")
        if self.download_status != 200:
            return httpx.Response(self.download_status, text="<Error>AccessDenied</Error>")
        for op in self.operations.values():
            if op["file"] == request.url.path:
                body = "\n".join(json.dumps(n) for n in op["nodes"]) + "\n"
                return httpx.Response(200, content=body.encode())
        return httpx.Response(404)

    def http_factory(self) -> SafeHttpClient:
        return SafeHttpClient(
            POLICY,
            resolver=lambda host, port: [PUBLIC_IP],
            transport=httpx.MockTransport(self.handler),
        )


def build_provider(sim: ShopifySim, clock: Clock, apps: tuple[ShopifyApp, ...] | None = None):
    from datetime import timedelta

    return ShopifyProvider(
        apps=apps or (ShopifyApp(CLIENT_ID, CLIENT_SECRET, frozenset({"*"})),),
        http_factory=sim.http_factory,
        api_version=API_VERSION,
        scopes=SCOPES,
        clock=clock,
        install_max_age=timedelta(minutes=5),
        default_order_history=timedelta(days=60),
    )


def callback_params(
    authorize_url: str,
    *,
    shop: str | None = None,
    code: str = "sim-code",
    secret: str = CLIENT_SECRET,
) -> dict[str, str]:
    """What Shopify sends back after approval: signed with the app's client secret."""
    parts = urlsplit(authorize_url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    params = {
        "code": code,
        "shop": shop or parts.hostname or "",
        "state": query["state"],
        "timestamp": str(int(time.time())),
        "host": "YWRtaW4uc2hvcGlmeS5jb20vc3RvcmUvdGVzdA",
    }
    params["hmac"] = sign_query(params, secret)
    return params


def install_params(shop: str, timestamp: int, secret: str = CLIENT_SECRET) -> dict[str, str]:
    params = {"shop": shop, "timestamp": str(timestamp), "host": "YWRtaW4"}
    params["hmac"] = sign_query(params, secret)
    return params


def query_string(params: dict[str, str]) -> str:
    return urlencode(params)


def webhook_request(
    topic: str,
    payload: dict[str, Any],
    *,
    shop: str,
    webhook_id: str,
    triggered_at: str | None = None,
    secret: str = CLIENT_SECRET,
) -> tuple[dict[str, str], bytes]:
    """A webhook delivery in Shopify's documented format: base64 HMAC-SHA256 of the raw body
    in ``X-Shopify-Hmac-Sha256`` plus the topic / shop / webhook-id / triggered-at headers."""
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Topic": topic,
        "X-Shopify-Hmac-Sha256": sign_body(body, secret),
        "X-Shopify-Shop-Domain": shop,
        "X-Shopify-Webhook-Id": webhook_id,
        "X-Shopify-API-Version": API_VERSION,
    }
    if triggered_at is not None:
        headers["X-Shopify-Triggered-At"] = triggered_at
    return headers, body


def strip(node: dict[str, Any]) -> dict[str, Any]:
    """A node as a GraphQL response returns it (no bulk ``__parentId``)."""
    return {k: v for k, v in node.items() if k != "__parentId"}


# ---------------------------------------------------------------- sample bulk exports
def money(amount: str, currency: str = "AUD") -> dict[str, Any]:
    return {"shopMoney": {"amount": amount, "currencyCode": currency}}


def sample_catalogue() -> list[dict[str, Any]]:
    """Two products, three variants: one costed + tracked, one uncosted, one untracked."""
    return [
        {
            "id": "gid://shopify/Product/1",
            "title": "Nitrile Gloves",
            "handle": "nitrile-gloves",
            "productType": "Gloves",
            "vendor": "Mediflex",
            "status": "ACTIVE",
            "updatedAt": "2026-10-01T00:00:00Z",
        },
        {
            "id": "gid://shopify/ProductVariant/11",
            "title": "Medium",
            "sku": "NG-M",
            "price": "19.90",
            "updatedAt": "2026-10-01T00:00:00Z",
            "inventoryQuantity": 120,
            "inventoryItem": {
                "id": "gid://shopify/InventoryItem/111",
                "tracked": True,
                "unitCost": {"amount": "7.25", "currencyCode": "AUD"},
            },
            "__parentId": "gid://shopify/Product/1",
        },
        {
            "id": "gid://shopify/ProductVariant/12",
            "title": "Large",
            "sku": "NG-L",
            "price": "21.90",
            "updatedAt": "2026-10-01T00:00:00Z",
            "inventoryQuantity": 0,
            "inventoryItem": {"id": "gid://shopify/InventoryItem/112", "tracked": True},
            "__parentId": "gid://shopify/Product/1",
        },
        {
            "id": "gid://shopify/Product/2",
            "title": "Gift Wrap",
            "handle": "gift-wrap",
            "productType": "",
            "vendor": "Eve Zone",
            "status": "UNLISTED",
            "updatedAt": "2026-10-02T00:00:00Z",
        },
        {
            "id": "gid://shopify/ProductVariant/21",
            "title": "Default Title",
            "sku": None,
            "price": "5.00",
            "updatedAt": "2026-10-02T00:00:00Z",
            "inventoryQuantity": -3,
            "inventoryItem": {
                "id": "gid://shopify/InventoryItem/211",
                "tracked": False,
                "unitCost": {"amount": "1.10", "currencyCode": "AUD"},
            },
            "__parentId": "gid://shopify/Product/2",
        },
    ]


def sample_orders() -> list[dict[str, Any]]:
    """One order with two lines, a sale per line plus shipping, then a partial return
    processed three days later; one test order (excluded). Children come after their parents,
    deliberately not grouped by order (as Shopify allows)."""
    order = {
        "id": "gid://shopify/Order/500",
        "name": "#1001",
        "processedAt": "2026-10-05T01:30:00Z",
        "updatedAt": "2026-10-08T03:00:00Z",
        "cancelledAt": None,
        "test": False,
        "currencyCode": "AUD",
        "displayFinancialStatus": "PARTIALLY_REFUNDED",
        "totalDiscountsSet": money("2.00"),
        "totalShippingPriceSet": money("10.00"),
        "totalTaxSet": money("5.80"),
        "totalRefundedSet": money("21.89"),
        "totalPriceSet": money("63.80"),
        "refunds": [
            {
                "id": "gid://shopify/Refund/900",
                "createdAt": "2026-10-08T03:00:00Z",
                "totalRefundedSet": money("21.89"),
            }
        ],
    }
    test_order = {
        **order,
        "id": "gid://shopify/Order/501",
        "name": "#1002",
        "test": True,
        "refunds": [],
    }
    return [
        order,
        test_order,
        {
            "id": "gid://shopify/LineItem/601",
            "title": "Nitrile Gloves - Medium",
            "sku": "NG-M",
            "quantity": 2,
            "variant": {"id": "gid://shopify/ProductVariant/11"},
            "originalUnitPriceSet": money("19.90"),
            "__parentId": "gid://shopify/Order/500",
        },
        {
            "id": "gid://shopify/SalesAgreement/700",
            "happenedAt": "2026-10-05T01:30:00Z",
            "reason": "ORDER",
            "__parentId": "gid://shopify/Order/500",
        },
        {
            "id": "gid://shopify/Sale/801",
            "actionType": "ORDER",
            "lineType": "PRODUCT",
            "quantity": 2,
            "totalAmount": money("41.58"),
            "totalDiscountAmountBeforeTaxes": money("2.00"),
            "totalTaxAmount": money("3.78"),
            "lineItem": {"id": "gid://shopify/LineItem/601"},
            "__parentId": "gid://shopify/SalesAgreement/700",
        },
        {
            # Sale arrives before its line item (no ordering guarantee between connections).
            "id": "gid://shopify/Sale/802",
            "actionType": "ORDER",
            "lineType": "PRODUCT",
            "quantity": 1,
            "totalAmount": money("12.11"),
            "totalDiscountAmountBeforeTaxes": money("0.00"),
            "totalTaxAmount": money("1.10"),
            "lineItem": {"id": "gid://shopify/LineItem/602"},
            "__parentId": "gid://shopify/SalesAgreement/700",
        },
        {
            "id": "gid://shopify/Sale/803",
            "actionType": "ORDER",
            "lineType": "SHIPPING",
            "quantity": None,
            "totalAmount": money("10.00"),
            "totalDiscountAmountBeforeTaxes": money("0.00"),
            "totalTaxAmount": money("0.92"),
            "__parentId": "gid://shopify/SalesAgreement/700",
        },
        {
            "id": "gid://shopify/LineItem/602",
            "title": "Custom engraving",
            "sku": None,
            "quantity": 1,
            "variant": None,
            "originalUnitPriceSet": money("11.01"),
            "__parentId": "gid://shopify/Order/500",
        },
        {
            "id": "gid://shopify/SalesAgreement/701",
            "happenedAt": "2026-10-08T03:00:00Z",
            "reason": "REFUND",
            "__parentId": "gid://shopify/Order/500",
        },
        {
            "id": "gid://shopify/Sale/804",
            "actionType": "RETURN",
            "lineType": "PRODUCT",
            "quantity": -1,
            "totalAmount": money("-20.79"),
            "totalDiscountAmountBeforeTaxes": money("-1.00"),
            "totalTaxAmount": money("-1.89"),
            "lineItem": {"id": "gid://shopify/LineItem/601"},
            "__parentId": "gid://shopify/SalesAgreement/701",
        },
        {
            "id": "gid://shopify/LineItem/699",
            "title": "Test line",
            "sku": "T",
            "quantity": 1,
            "variant": None,
            "originalUnitPriceSet": money("1.00"),
            "__parentId": "gid://shopify/Order/501",
        },
        {
            "id": "gid://shopify/SalesAgreement/799",
            "happenedAt": "2026-10-05T01:30:00Z",
            "reason": "ORDER",
            "__parentId": "gid://shopify/Order/501",
        },
        {
            "id": "gid://shopify/Sale/899",
            "actionType": "ORDER",
            "lineType": "PRODUCT",
            "quantity": 1,
            "totalAmount": money("1.00"),
            "totalDiscountAmountBeforeTaxes": money("0.00"),
            "totalTaxAmount": money("0.00"),
            "__parentId": "gid://shopify/SalesAgreement/799",
        },
    ]


def add_order(shop: Shop, number: int = 600, processed: str = "2026-10-12T02:00:00Z") -> str:
    """Adds a paid order (2 x Nitrile Gloves Medium, 39.80 incl. 3.62 tax) to the store."""
    oid = f"gid://shopify/Order/{number}"
    template = next(n for n in shop.orders if n["id"] == "gid://shopify/Order/500")
    order = {
        **template,
        "id": oid,
        "name": f"#{number}",
        "processedAt": processed,
        "updatedAt": processed,
        "displayFinancialStatus": "PAID",
        "totalDiscountsSet": money("0.00"),
        "totalShippingPriceSet": money("0.00"),
        "totalTaxSet": money("3.62"),
        "totalRefundedSet": money("0.00"),
        "totalPriceSet": money("39.80"),
        "refunds": [],
    }
    shop.orders.extend(
        [
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
    )
    return oid
