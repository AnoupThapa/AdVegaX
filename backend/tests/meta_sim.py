"""In-process Meta login and Graph API simulator for tests (Phase 4, PLAN §14).

Speaks the documented formats (checked 2026-10-18) behind the real ``SafeHttpClient`` (a fake
resolver returns a public address; the transport is ``httpx.MockTransport``):

* the browser side of Facebook Login for Business (``approve``): configuration id, ``state``,
  PKCE S256;
* ``POST /oauth/access_token``: code exchange (PKCE verifier and app secret checked) and the
  long-lived exchange (``fb_exchange_token``, about 60 days);
* ``GET /me``, ``GET /me/permissions`` and ``DELETE /me/permissions``;
* ``GET /me/adaccounts`` (``limit`` / ``after`` cursor paging) and ``GET /act_<id>`` for the
  ad accounts a user can reach (task 4-03);
* every other call: the token must be known and unexpired and ``appsecret_proof`` must match;
  errors use Meta's ``{"error": {"code", "error_subcode", "type", "message"}}`` shape; usage
  headers can be set per answer.

Graph reads for discovery, structure and insights are added with tasks 4-03 … 4-05 through
``routes``. Records every request. No network — CI never calls Meta.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from app.core.clock import Clock
from app.providers.http.client import OutboundPolicy, SafeHttpClient
from app.providers.meta_ads.provider import MetaAdsProvider

APP_ID = "1234567890123"
APP_SECRET = "test-meta-app-secret-0123456789abcdef"
CONFIG_ID = "9876543210"
API_VERSION = "v26.0"
PUBLIC_IP = "157.240.22.35"
LONG_LIVED_SECONDS = 60 * 24 * 3600
SHORT_LIVED_SECONDS = 2 * 3600
POLICY = OutboundPolicy(
    connect_timeout=1, read_timeout=1, max_response_bytes=5_000_000, max_redirects=0
)

Route = Callable[["MetaSim", httpx.Request, str], httpx.Response]


@dataclass
class MetaUser:
    id: str
    granted: list[str] = field(default_factory=lambda: ["ads_read", "business_management"])
    declined: list[str] = field(default_factory=list)


@dataclass
class AdAccount:
    id: str  # "act_123"
    name: str = "Shop account"
    currency: str | None = "EUR"
    timezone_name: str | None = "Europe/Berlin"
    account_status: int = 1
    business: tuple[str, str] | None = ("555000111", "Eve Zone Business")
    users: set[str] = field(default_factory=set)

    def row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "account_status": self.account_status,
        }
        if self.currency is not None:
            row["currency"] = self.currency
        if self.timezone_name is not None:
            row["timezone_name"] = self.timezone_name
        if self.business is not None:
            row["business"] = {"id": self.business[0], "name": self.business[1]}
        return row


@dataclass
class MetaSim:
    clock: Clock
    users: dict[str, MetaUser] = field(default_factory=dict)
    # Token → (user id, expires at, long-lived).
    tokens: dict[str, tuple[str, float, bool]] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)  # tokens ended by DELETE /me/permissions
    requests: list[httpx.Request] = field(default_factory=list)
    routes: dict[str, Route] = field(default_factory=dict)  # "GET /me" → handler (4-03 …)
    fail_next: list[tuple[int, int, int | None]] = field(default_factory=list)
    usage_headers: dict[str, str] = field(default_factory=dict)
    token_expiry_seconds: int = LONG_LIVED_SECONDS
    accounts: dict[str, AdAccount] = field(default_factory=dict)
    extra_rows: list[dict[str, Any]] = field(default_factory=list)  # odd rows for skip tests
    _codes: dict[str, dict[str, str]] = field(default_factory=dict)
    issued: int = 0

    # ------------------------------------------------------------------ setup helpers
    def add_user(self, user_id: str, *granted: str) -> MetaUser:
        user = MetaUser(user_id, list(granted) if granted else ["ads_read", "business_management"])
        self.users[user_id] = user
        return user

    def add_account(self, account_id: str, *users: str, **fields: Any) -> AdAccount:
        account = AdAccount(account_id, users=set(users), **fields)
        self.accounts[account_id] = account
        return account

    def calls(self, part: str) -> list[httpx.Request]:
        return [r for r in self.requests if part in r.url.path]

    def new_token(self, user_id: str, *, long_lived: bool = True) -> str:
        self.issued += 1
        kind = "long" if long_lived else "short"
        token = f"EAAsim{kind}{self.issued}{secrets.token_hex(8)}"
        life = self.token_expiry_seconds if long_lived else SHORT_LIVED_SECONDS
        self.tokens[token] = (user_id, self.clock.now().timestamp() + life, long_lived)
        return token

    # ------------------------------------------------------------------ browser side
    def approve(
        self,
        authorize_url: str,
        user_id: str,
        *,
        declined: bool = False,
    ) -> dict[str, str]:
        """Play the person on Meta's login dialog; return the callback parameters."""
        parts = urlsplit(authorize_url)
        assert (parts.hostname, parts.path) == ("www.facebook.com", f"/{API_VERSION}/dialog/oauth")
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert query["client_id"] == APP_ID
        assert query["config_id"] == CONFIG_ID
        assert query["response_type"] == "code"
        assert query["code_challenge_method"] == "S256"
        assert "scope" not in query  # Login for Business: the configuration decides
        if declined:
            return {
                "error": "access_denied",
                "error_reason": "user_denied",
                "error_description": "Permissions error",
                "state": query["state"],
            }
        code = f"sim-meta-code-{secrets.token_hex(8)}"
        self._codes[code] = {
            "user": user_id,
            "challenge": query["code_challenge"],
            "redirect_uri": query["redirect_uri"],
        }
        return {"code": code, "state": query["state"]}

    # ------------------------------------------------------------------ server side
    @staticmethod
    def error(status: int, code: int, subcode: int | None = None) -> httpx.Response:
        body: dict[str, Any] = {
            "message": "Simulated Meta error.",
            "type": "OAuthException",
            "code": code,
            "fbtrace_id": "SimTrace",
        }
        if subcode is not None:
            body["error_subcode"] = subcode
        return httpx.Response(status, json={"error": body})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("host", "") != "graph.facebook.com":
            return httpx.Response(404, text="not found")
        prefix = f"/{API_VERSION}"
        if not request.url.path.startswith(prefix):
            return self.error(400, 2635)  # unsupported version
        route = request.url.path[len(prefix) :]
        response = self._route(request, route)
        for name, value in self.usage_headers.items():
            response.headers[name] = value
        return response

    def _route(self, request: httpx.Request, route: str) -> httpx.Response:
        if route == "/oauth/access_token" and request.method == "POST":
            return self._exchange(request)
        if self.fail_next:
            status, code, subcode = self.fail_next.pop(0)
            return self.error(status, code, subcode)
        bearer = request.headers.get("authorization", "")
        token = bearer.removeprefix("Bearer ")
        query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        if "access_token" in query:
            return self.error(400, 100)  # AdVegaX never sends tokens in the address
        if not bearer.startswith("Bearer ") or token not in self.tokens:
            return self.error(400, 190, 467)
        proof = hmac.new(APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
        if query.get("appsecret_proof") != proof:
            return self.error(400, 100)  # "Invalid appsecret_proof"
        user_id, expires, _ = self.tokens[token]
        if expires < self.clock.now().timestamp():
            return self.error(400, 190, 463)
        if route == "/me/permissions" and request.method == "DELETE":
            for other in [t for t, v in self.tokens.items() if v[0] == user_id]:
                self.tokens.pop(other)
                self.removed.append(other)
            return httpx.Response(200, json={"success": True})
        if route == "/me" and request.method == "GET":
            return httpx.Response(200, json={"id": user_id})
        if route == "/me/permissions" and request.method == "GET":
            user = self.users.get(user_id, MetaUser(user_id))
            rows = [{"permission": p, "status": "granted"} for p in user.granted]
            rows += [{"permission": p, "status": "declined"} for p in user.declined]
            return httpx.Response(200, json={"data": rows})
        handler = self.routes.get(f"{request.method} {route}")
        if handler is not None:
            return handler(self, request, user_id)
        if route == "/me/adaccounts" and request.method == "GET":
            return self._ad_accounts(query, user_id)
        if request.method == "GET" and re.fullmatch(r"/act_[0-9]+", route):
            account = self.accounts.get(route[1:])
            if account is None or user_id not in account.users:
                return self.error(400, 100, 33)
            return httpx.Response(200, json=account.row())
        return self.error(400, 100)

    def _ad_accounts(self, query: dict[str, str], user_id: str) -> httpx.Response:
        rows = [a.row() for a in self.accounts.values() if user_id in a.users] + self.extra_rows
        limit = int(query.get("limit", "25"))
        start = int(query["after"].removeprefix("cur")) if "after" in query else 0
        page = rows[start : start + limit]
        body: dict[str, Any] = {"data": page}
        if start + limit < len(rows):
            body["paging"] = {
                "cursors": {"before": f"cur{start}", "after": f"cur{start + limit}"},
                "next": "https://graph.facebook.com/v26.0/me/adaccounts?after=elided",
            }
        return httpx.Response(200, json=body)

    def _exchange(self, request: httpx.Request) -> httpx.Response:
        if request.url.query:
            return self.error(400, 100)  # the app secret must not travel in the address
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if form.get("client_id") != APP_ID or form.get("client_secret") != APP_SECRET:
            return self.error(400, 101)  # invalid client
        if form.get("grant_type") == "fb_exchange_token":
            entry = self.tokens.get(form.get("fb_exchange_token", ""))
            if entry is None or entry[1] < self.clock.now().timestamp():
                return self.error(400, 190, 463)
            token = self.new_token(entry[0], long_lived=True)
            return httpx.Response(
                200,
                json={
                    "access_token": token,
                    "token_type": "bearer",
                    "expires_in": self.token_expiry_seconds,
                },
            )
        entry = self._codes.pop(form.get("code", ""), None)
        if entry is None or entry["redirect_uri"] != form.get("redirect_uri"):
            return self.error(400, 100, 36007)  # code already used or not issued
        digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
        if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != entry["challenge"]:
            return self.error(400, 100)
        token = self.new_token(entry["user"], long_lived=False)
        return httpx.Response(
            200,
            json={"access_token": token, "token_type": "bearer", "expires_in": SHORT_LIVED_SECONDS},
        )

    def http_factory(self) -> SafeHttpClient:
        return SafeHttpClient(
            POLICY,
            resolver=lambda host, port: [PUBLIC_IP],
            transport=httpx.MockTransport(self.handler),
        )


def build_provider(sim: MetaSim, *, burst: int = 1000) -> MetaAdsProvider:
    """As for the Google Ads simulator: the frozen test clock never refills the per-connection
    limiter, so tests get a large burst unless they test the limit itself."""
    provider = MetaAdsProvider(
        app_id=APP_ID,
        app_secret=APP_SECRET,
        login_config_id=CONFIG_ID,
        api_version=API_VERSION,
        http_factory=sim.http_factory,
        clock=sim.clock,
    )
    rate, _ = provider.rate_limit
    provider.rate_limit = (rate, burst)
    return provider


def usage(percent: int, *, regain_minutes: int = 0, account: str = "act_1") -> dict[str, str]:
    """Usage headers as Meta sends them, all at ``percent``."""
    return {
        "x-business-use-case-usage": json.dumps(
            {
                account: [
                    {
                        "type": "ads_insights",
                        "call_count": percent,
                        "total_cputime": percent,
                        "total_time": percent,
                        "estimated_time_to_regain_access": regain_minutes,
                        "ads_api_access_tier": "development_access",
                    }
                ]
            }
        ),
        "x-fb-ads-insights-throttle": json.dumps(
            {"app_id_util_pct": percent, "acc_id_util_pct": percent}
        ),
    }
