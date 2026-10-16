"""In-process Google sign-in and Google Ads API simulator for tests (Phase 3, PLAN §14).

Speaks the documented formats (verified 2026-10-15) behind the real ``SafeHttpClient`` (a
fake resolver returns a public address; the transport is ``httpx.MockTransport``):

* Google's OAuth 2.0 server: the browser-side consent (``approve``), the token endpoint (code
  exchange with PKCE S256, refresh, ``invalid_grant``) and token revocation;
* Google Ads REST: ``customers:listAccessibleCustomers``, ``googleAds:search`` (paged with
  ``nextPageToken``) and ``googleAds:searchStream``, with the ``developer-token`` and
  ``login-customer-id`` rules, access through manager accounts, test vs production accounts,
  and errors in Google's ``GoogleAdsFailure`` shape.

GAQL is not parsed here: tests (and later tasks' fixtures) register a ``query_handler`` that
answers the queries AdVegaX sends. Records every request. No network — CI never calls Google.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from app.core.clock import Clock
from app.providers.google_ads.provider import GoogleAdsProvider
from app.providers.http.client import OutboundPolicy, SafeHttpClient

CLIENT_ID = "test-client.apps.googleusercontent.com"
CLIENT_SECRET = "test-google-client-secret-0123456789"
DEVELOPER_TOKEN = "test-developer-token-ABCDEFGH"
API_VERSION = "v25"
ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
PUBLIC_IP = "142.250.70.10"
POLICY = OutboundPolicy(
    connect_timeout=1, read_timeout=1, max_response_bytes=5_000_000, max_redirects=0
)
FAILURE_TYPE = f"type.googleapis.com/google.ads.googleads.{API_VERSION}.errors.GoogleAdsFailure"


@dataclass
class Customer:
    id: str
    name: str = "Eve Zone Ads"
    currency: str = "AUD"
    timezone: str = "Australia/Sydney"
    manager: bool = False
    status: str = "ENABLED"  # ENABLED | CANCELED | SUSPENDED | CLOSED
    test: bool = True
    children: list[str] = field(default_factory=list)  # for managers: directly linked ids


@dataclass
class GoogleUser:
    sub: str
    direct: list[str] = field(default_factory=list)  # customer ids with direct access


QueryHandler = Callable[["GoogleAdsSim", str, str, str | None], list[dict[str, Any]]]


def _no_rows(sim: GoogleAdsSim, customer_id: str, query: str, login: str | None) -> list[Any]:
    return []


@dataclass
class GoogleAdsSim:
    clock: Clock
    customers: dict[str, Customer] = field(default_factory=dict)
    users: dict[str, GoogleUser] = field(default_factory=dict)
    developer_token: str = DEVELOPER_TOKEN
    token_access: str = "test"  # test | explorer | basic | standard
    query_handler: QueryHandler = _no_rows
    page_size: int = 10_000
    stream_batch_size: int = 10_000
    requests: list[httpx.Request] = field(default_factory=list)
    # Forced failures: the next Google Ads call answers this (status, errorCode dict) once.
    fail_next: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    token_status: int | None = None  # force the token endpoint's status (e.g. 503)
    send_new_refresh_on_refresh: bool = False
    _codes: dict[str, dict[str, str]] = field(default_factory=dict)
    access_tokens: dict[str, tuple[str, float]] = field(default_factory=dict)
    refresh_tokens: dict[str, str] = field(default_factory=dict)
    revoked: list[str] = field(default_factory=list)
    issued: int = 0

    # ------------------------------------------------------------------ setup helpers
    def add_customer(self, customer_id: str, **kw: Any) -> Customer:
        customer = Customer(customer_id, **kw)
        self.customers[customer_id] = customer
        return customer

    def add_user(self, sub: str, *direct: str) -> GoogleUser:
        user = GoogleUser(sub, list(direct))
        self.users[sub] = user
        return user

    def calls(self, part: str) -> list[httpx.Request]:
        return [r for r in self.requests if part in r.url.path]

    def reachable(self, sub: str, login: str | None) -> set[str]:
        """Accounts the user can call with this ``login-customer-id`` (Google's access model)."""
        user = self.users.get(sub)
        if user is None:
            return set()
        if not login:  # without login-customer-id only direct access counts
            return set(user.direct)
        if login not in user.direct and not any(login in self._below(d) for d in user.direct):
            return set()
        return {login, *self._below(login)}

    def _below(self, customer_id: str) -> set[str]:
        found: set[str] = set()
        stack = list(self.customers.get(customer_id, Customer(customer_id)).children)
        while stack:
            child = stack.pop()
            if child not in found:
                found.add(child)
                stack.extend(self.customers.get(child, Customer(child)).children)
        return found

    # ------------------------------------------------------------------ browser side
    def approve(
        self,
        authorize_url: str,
        sub: str,
        *,
        scopes: str | None = None,
        declined: bool = False,
    ) -> dict[str, str]:
        """Play the person on Google's consent screen; return the callback parameters."""
        parts = urlsplit(authorize_url)
        assert (parts.hostname, parts.path) == ("accounts.google.com", "/o/oauth2/v2/auth")
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert query["client_id"] == CLIENT_ID
        assert query["access_type"] == "offline"
        assert query["code_challenge_method"] == "S256"
        if declined:
            return {"error": "access_denied", "state": query["state"]}
        granted = scopes if scopes is not None else query["scope"]
        code = f"sim-code-{secrets.token_hex(8)}"
        self._codes[code] = {
            "sub": sub,
            "challenge": query["code_challenge"],
            "redirect_uri": query["redirect_uri"],
            "scope": granted,
        }
        return {"code": code, "state": query["state"], "scope": granted}

    # ------------------------------------------------------------------ server side
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.headers.get("host", "")
        if host == "oauth2.googleapis.com":
            return self._oauth(request)
        if host == "googleads.googleapis.com":
            return self._ads(request)
        return httpx.Response(404, text="not found")

    def _id_token(self, sub: str) -> str:
        def part(data: dict[str, Any]) -> str:
            raw = json.dumps(data, separators=(",", ":")).encode()
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

        now = int(self.clock.now().timestamp())
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": sub}
        claims |= {"iat": now, "exp": now + 3600}
        return f"{part({'alg': 'RS256', 'typ': 'JWT'})}.{part(claims)}.c2lnbmF0dXJl"

    def _new_access(self, sub: str) -> str:
        self.issued += 1
        token = f"ya29.sim-access-{self.issued}-{secrets.token_hex(6)}"
        self.access_tokens[token] = (sub, self.clock.now().timestamp() + 3599)
        return token

    def _oauth(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if request.url.path == "/revoke":
            token = form.get("token", "")
            if token in self.refresh_tokens:
                sub = self.refresh_tokens.pop(token)
                self.access_tokens = {k: v for k, v in self.access_tokens.items() if v[0] != sub}
                self.revoked.append(token)
                return httpx.Response(200, json={})
            if token in self.access_tokens:
                self.access_tokens.pop(token)
                self.revoked.append(token)
                return httpx.Response(200, json={})
            return httpx.Response(400, json={"error": "invalid_token"})
        if request.url.path != "/token":
            return httpx.Response(404, json={"error": "not_found"})
        if self.token_status is not None:
            return httpx.Response(self.token_status, json={"error": "backend_error"})
        if form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET:
            return httpx.Response(401, json={"error": "invalid_client"})
        grant = form.get("grant_type")
        if grant == "authorization_code":
            entry = self._codes.pop(form.get("code", ""), None)
            if entry is None or entry["redirect_uri"] != form.get("redirect_uri"):
                return httpx.Response(400, json={"error": "invalid_grant"})
            verifier = form.get("code_verifier", "")
            digest = hashlib.sha256(verifier.encode()).digest()
            if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != entry["challenge"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            refresh = f"1//sim-refresh-{secrets.token_hex(10)}"
            self.refresh_tokens[refresh] = entry["sub"]
            body = {
                "access_token": self._new_access(entry["sub"]),
                "expires_in": 3599,
                "refresh_token": refresh,
                "scope": entry["scope"],
                "token_type": "Bearer",
                "id_token": self._id_token(entry["sub"]),
            }
            return httpx.Response(200, json=body)
        if grant == "refresh_token":
            refresh = form.get("refresh_token", "")
            sub = self.refresh_tokens.get(refresh)
            if sub is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            body = {
                "access_token": self._new_access(sub),
                "expires_in": 3599,
                "scope": f"{ADS_SCOPE} openid",
                "token_type": "Bearer",
            }
            if self.send_new_refresh_on_refresh:
                new = f"1//sim-refresh-{secrets.token_hex(10)}"
                self.refresh_tokens[new] = self.refresh_tokens.pop(refresh)
                body["refresh_token"] = new
            return httpx.Response(200, json=body)
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    @staticmethod
    def failure(status: int, error_code: dict[str, str]) -> httpx.Response:
        names = {400: "INVALID_ARGUMENT", 401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED"}
        names |= {429: "RESOURCE_EXHAUSTED", 500: "INTERNAL"}
        detail = {
            "@type": FAILURE_TYPE,
            "errors": [{"errorCode": error_code, "message": "Simulated Google Ads error."}],
            "requestId": "sim-request",
        }
        return httpx.Response(
            status,
            json={
                "error": {
                    "code": status,
                    "message": "Request contains an invalid argument.",
                    "status": names.get(status, "UNKNOWN"),
                    "details": [detail],
                }
            },
        )

    def _ads(self, request: httpx.Request) -> httpx.Response:
        prefix = f"/{API_VERSION}"
        path = request.url.path
        if not path.startswith(prefix):
            return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND"}})
        route = path[len(prefix) :]
        if self.fail_next:
            status, error_code = self.fail_next.pop(0)
            return self.failure(status, error_code)
        if request.headers.get("developer-token") != self.developer_token:
            return self.failure(401, {"authenticationError": "DEVELOPER_TOKEN_INVALID"})
        bearer = request.headers.get("authorization", "")
        entry = self.access_tokens.get(bearer.removeprefix("Bearer "))
        if not bearer.startswith("Bearer ") or entry is None:
            return self.failure(401, {"authenticationError": "OAUTH_TOKEN_INVALID"})
        sub, expires = entry
        if expires < self.clock.now().timestamp():
            return self.failure(401, {"authenticationError": "OAUTH_TOKEN_EXPIRED"})
        if route == "/customers:listAccessibleCustomers" and request.method == "GET":
            user = self.users.get(sub)
            if user is None or not user.direct:
                return self.failure(403, {"authenticationError": "NOT_ADS_USER"})
            return httpx.Response(
                200, json={"resourceNames": [f"customers/{c}" for c in user.direct]}
            )
        if request.method != "POST" or not route.startswith("/customers/"):
            return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND"}})
        customer_id, _, method = route.removeprefix("/customers/").partition("/googleAds:")
        if method not in ("search", "searchStream"):
            return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND"}})
        login = request.headers.get("login-customer-id")
        customer = self.customers.get(customer_id)
        if customer is None or customer_id not in self.reachable(sub, login):
            return self.failure(403, {"authorizationError": "USER_PERMISSION_DENIED"})
        if not customer.test and self.token_access == "test":
            return self.failure(403, {"authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"})
        if customer.status != "ENABLED":
            return self.failure(403, {"authorizationError": "CUSTOMER_NOT_ENABLED"})
        body = json.loads(request.content or b"{}")
        query = str(body.get("query", ""))
        if not query.strip().upper().startswith("SELECT"):
            return self.failure(400, {"queryError": "UNEXPECTED_END_OF_QUERY"})
        rows = self.query_handler(self, customer_id, query, login)
        if method == "searchStream":
            size = max(1, self.stream_batch_size)
            batches = [rows[i : i + size] for i in range(0, len(rows), size)] or [[]]
            return httpx.Response(
                200,
                json=[{"results": b, "fieldMask": "x", "requestId": "sim"} for b in batches],
            )
        start = int(body.get("pageToken") or 0)
        page = rows[start : start + self.page_size]
        answer: dict[str, Any] = {"results": page, "fieldMask": "x"}
        if start + self.page_size < len(rows):
            answer["nextPageToken"] = str(start + self.page_size)
        return httpx.Response(200, json=answer)

    def http_factory(self) -> SafeHttpClient:
        return SafeHttpClient(
            POLICY,
            resolver=lambda host, port: [PUBLIC_IP],
            transport=httpx.MockTransport(self.handler),
        )


def build_provider(sim: GoogleAdsSim) -> GoogleAdsProvider:
    return GoogleAdsProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        developer_token=DEVELOPER_TOKEN,
        api_version=API_VERSION,
        http_factory=sim.http_factory,
        clock=sim.clock,
    )


def sample_hierarchy(sim: GoogleAdsSim) -> GoogleAdsSim:
    """Agency manager 9000000001 → retail manager 9000000002 → two advertiser accounts (AUD in
    Sydney, NZD in Auckland); plus 1000000003 with direct access, and a cancelled account."""
    sim.add_customer("9000000001", name="Agency", manager=True, children=["9000000002"])
    sim.add_customer(
        "9000000002", name="Retail clients", manager=True, children=["1000000001", "1000000002"]
    )
    sim.add_customer("1000000001", name="Eve Zone AU")
    sim.add_customer("1000000002", name="Eve Zone NZ", currency="NZD", timezone="Pacific/Auckland")
    sim.add_customer("1000000003", name="Mediflex", currency="AUD")
    sim.add_customer("1000000004", name="Old account", status="CANCELED")
    sim.add_user("108000000000000000001", "9000000001", "1000000003", "1000000004")
    return sim
