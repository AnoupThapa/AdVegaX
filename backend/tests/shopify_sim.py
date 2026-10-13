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
from app.providers.shopify.signatures import sign_query

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


@dataclass
class ShopifySim:
    shops: dict[str, Shop] = field(default_factory=dict)
    granted_scope: str = ",".join(SCOPES)
    token_status: int = 200
    graphql_status: int = 200
    graphql_errors: list[dict[str, Any]] | None = None
    requests: list[httpx.Request] = field(default_factory=list)
    issued: int = 0

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
            if form.get("refresh_token") != f"shprt_sim_refresh_{self.issued}":
                return httpx.Response(400, json={"error": "invalid_grant"})
            form["expiring"] = "1"
        elif not form.get("code"):
            return httpx.Response(400, json={"error": "invalid_request"})
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

    def _graphql(self, request: httpx.Request, shop: Shop) -> httpx.Response:
        if request.headers.get("x-shopify-access-token", "").startswith("shpat_sim_") is False:
            return httpx.Response(401, json={"errors": "[API] Invalid API key or access token"})
        if self.graphql_status != 200:
            headers = {"Retry-After": "2.0"} if self.graphql_status == 429 else {}
            return httpx.Response(self.graphql_status, headers=headers, json={"errors": "x"})
        if self.graphql_errors:
            return httpx.Response(200, json={"errors": self.graphql_errors})
        query = json.loads(request.content)["query"]
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
