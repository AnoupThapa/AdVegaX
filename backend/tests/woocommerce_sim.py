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
    data: dict[str, Any] = field(default_factory=dict)  # route → JSON (later tasks)


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
        if route[len("/wc/v3") :] in store.data:
            return httpx.Response(200, json=store.data[route[len("/wc/v3") :]])
        return _error(404, "rest_no_route")

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


def _error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"code": code, "message": "x", "data": {"status": status}})


def build_provider(sim: WooSim, **kw: Any) -> WooCommerceProvider:
    return WooCommerceProvider(http_factory=sim.http_factory, **kw)


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
