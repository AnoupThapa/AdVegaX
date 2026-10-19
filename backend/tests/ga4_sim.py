"""In-process Google Analytics 4 simulator for tests (Phase 5, PLAN §14).

Speaks the documented formats (checked 2026-10-19) behind the real ``SafeHttpClient`` (a fake
resolver returns a public address; the transport is ``httpx.MockTransport``):

* Google's sign-in, shared with the Google Ads simulator (``tests/google_oauth_sim.py``);
* Admin API ``v1beta``: ``GET accountSummaries`` (paged with ``nextPageToken``) and
  ``GET properties/<id>`` (currency, time zone, ``deleteTime`` for a property in the bin);
* Data API ``v1beta``: ``POST properties/<id>:batchRunReports`` and ``:runReport``, answered by
  a ``report_handler`` (task 5-05 adds sample reports), with the ``propertyQuota`` block when
  asked for it;
* every call needs a known, unexpired token in the ``Authorization`` header and
  ``analytics.readonly``; errors use Google's ``{"error": {"code", "status", "details"}}``
  shape (``SERVICE_DISABLED``, ``ACCESS_TOKEN_SCOPE_INSUFFICIENT``, ``RESOURCE_EXHAUSTED``…).

Records every request. No network — CI never calls Google.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx
from app.providers.google_analytics.provider import GoogleAnalyticsProvider
from app.providers.http.client import OutboundPolicy, SafeHttpClient

from tests.google_oauth_sim import CLIENT_ID, CLIENT_SECRET, GoogleOAuthSim

ANALYTICS_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
API_VERSION = "v1beta"
PUBLIC_IP = "142.250.70.14"
POLICY = OutboundPolicy(
    connect_timeout=1, read_timeout=1, max_response_bytes=5_000_000, max_redirects=0
)
DAY_TOKENS, HOUR_TOKENS, PROJECT_HOUR_TOKENS = 200_000, 40_000, 14_000

ReportHandler = Callable[["GA4Sim", str, dict[str, Any]], dict[str, Any]]


@dataclass
class GA4Property:
    id: str  # digits
    account: str  # digits
    display_name: str = "Shop"
    currency: str | None = "AUD"
    time_zone: str | None = "Australia/Sydney"
    deleted: bool = False
    users: set[str] = field(default_factory=set)  # Google account ids with access


@dataclass
class GA4Account:
    id: str
    display_name: str = "Eve Zone"


def _empty_report(sim: GA4Sim, property_id: str, request: dict[str, Any]) -> dict[str, Any]:
    return {
        "dimensionHeaders": [{"name": d["name"]} for d in request.get("dimensions", [])],
        "metricHeaders": [{"name": m["name"]} for m in request.get("metrics", [])],
        "rowCount": 0,
        "metadata": {"currencyCode": sim.properties[property_id].currency or "USD"},
        "kind": "analyticsData#runReport",
    }


@dataclass
class GA4Sim(GoogleOAuthSim):
    accounts: dict[str, GA4Account] = field(default_factory=dict)
    properties: dict[str, GA4Property] = field(default_factory=dict)
    report_handler: ReportHandler = _empty_report
    page_size_cap: int = 200
    # Forced failures for the next Analytics call: (HTTP status, Google status, reason).
    fail_next: list[tuple[int, str, str | None]] = field(default_factory=list)
    api_enabled: bool = True
    report_cost: int = 10  # tokens a report uses
    day_used: dict[str, int] = field(default_factory=dict)
    hour_used: dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------------ setup helpers
    def add_account(self, account_id: str, name: str = "Eve Zone") -> GA4Account:
        account = GA4Account(account_id, name)
        self.accounts[account_id] = account
        return account

    def add_property(
        self, property_id: str, account_id: str, *users: str, **kw: Any
    ) -> GA4Property:
        if account_id not in self.accounts:
            self.add_account(account_id)
        prop = GA4Property(property_id, account_id, users=set(users), **kw)
        self.properties[property_id] = prop
        return prop

    # ------------------------------------------------------------------ server side
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.headers.get("host", "")
        if host == "oauth2.googleapis.com":
            return self._oauth(request)
        if host in ("analyticsadmin.googleapis.com", "analyticsdata.googleapis.com"):
            return self._analytics(request, host)
        return httpx.Response(404, text="not found")

    @staticmethod
    def failure(status: int, state: str, reason: str | None = None) -> httpx.Response:
        error: dict[str, Any] = {"code": status, "message": "Simulated error.", "status": state}
        if reason is not None:
            error["details"] = [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": reason,
                    "domain": "googleapis.com",
                }
            ]
        return httpx.Response(status, json={"error": error})

    def _user(self, request: httpx.Request) -> str | httpx.Response:
        bearer = request.headers.get("authorization", "")
        token = bearer.removeprefix("Bearer ")
        entry = self.access_tokens.get(token)
        if not bearer.startswith("Bearer ") or entry is None:
            return self.failure(401, "UNAUTHENTICATED")
        sub, expires = entry
        if expires < self.clock.now().timestamp():
            return self.failure(401, "UNAUTHENTICATED")
        if not any(
            ANALYTICS_SCOPE in self.refresh_scopes.get(r, "").split()
            for r, s in self.refresh_tokens.items()
            if s == sub
        ):
            return self.failure(403, "PERMISSION_DENIED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT")
        return sub

    def _analytics(self, request: httpx.Request, host: str) -> httpx.Response:
        if "access_token" in request.url.query.decode() or "key=" in request.url.query.decode():
            return self.failure(400, "INVALID_ARGUMENT")  # AdVegaX never sends tokens in URLs
        user = self._user(request)
        if isinstance(user, httpx.Response):
            return user
        if not self.api_enabled:
            return self.failure(403, "PERMISSION_DENIED", "SERVICE_DISABLED")
        if self.fail_next:
            status, state, reason = self.fail_next.pop(0)
            return self.failure(status, state, reason)
        prefix = f"/{API_VERSION}/"
        path = request.url.path
        if not path.startswith(prefix):
            return self.failure(404, "NOT_FOUND")
        rest = path[len(prefix) :]
        query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        if host == "analyticsadmin.googleapis.com" and request.method == "GET":
            if rest == "accountSummaries":
                return self._summaries(user, query)
            found = re.fullmatch(r"properties/([0-9]+)", rest)
            if found:
                return self._property(user, found.group(1))
        if host == "analyticsdata.googleapis.com" and request.method == "POST":
            found = re.fullmatch(r"properties/([0-9]+):(runReport|batchRunReports)", rest)
            if found:
                return self._reports(user, found.group(1), found.group(2), request)
        return self.failure(404, "NOT_FOUND")

    def _visible(self, user: str) -> list[GA4Property]:
        return [p for p in self.properties.values() if user in p.users and not p.deleted]

    def _summaries(self, user: str, query: dict[str, str]) -> httpx.Response:
        by_account: dict[str, list[GA4Property]] = {}
        for prop in self._visible(user):
            by_account.setdefault(prop.account, []).append(prop)
        rows = [
            {
                "name": f"accountSummaries/{account}",
                "account": f"accounts/{account}",
                "displayName": self.accounts[account].display_name,
                "propertySummaries": [
                    {
                        "property": f"properties/{p.id}",
                        "displayName": p.display_name,
                        "propertyType": "PROPERTY_TYPE_ORDINARY",
                        "parent": f"accounts/{account}",
                    }
                    for p in props
                ],
            }
            for account, props in sorted(by_account.items())
        ]
        size = min(int(query.get("pageSize", "50")), self.page_size_cap)
        start = int(query.get("pageToken", "0") or 0)
        body: dict[str, Any] = {"accountSummaries": rows[start : start + size]}
        if start + size < len(rows):
            body["nextPageToken"] = str(start + size)
        return httpx.Response(200, json=body)

    def _property(self, user: str, property_id: str) -> httpx.Response:
        prop = self.properties.get(property_id)
        if prop is None or user not in prop.users:
            return self.failure(403, "PERMISSION_DENIED")
        body: dict[str, Any] = {
            "name": f"properties/{prop.id}",
            "propertyType": "PROPERTY_TYPE_ORDINARY",
            "parent": f"accounts/{prop.account}",
            "account": f"accounts/{prop.account}",
            "displayName": prop.display_name,
            "industryCategory": "SHOPPING",
            "serviceLevel": "GOOGLE_ANALYTICS_STANDARD",
            "createTime": "2024-01-15T00:00:00Z",
        }
        if prop.currency is not None:
            body["currencyCode"] = prop.currency
        if prop.time_zone is not None:
            body["timeZone"] = prop.time_zone
        if prop.deleted:
            body["deleteTime"] = "2026-10-01T00:00:00Z"
            body["expireTime"] = "2026-11-05T00:00:00Z"
        return httpx.Response(200, json=body)

    def _quota(self, property_id: str) -> dict[str, Any]:
        day, hour = self.day_used.get(property_id, 0), self.hour_used.get(property_id, 0)
        return {
            "tokensPerDay": {"consumed": self.report_cost, "remaining": max(0, DAY_TOKENS - day)},
            "tokensPerHour": {
                "consumed": self.report_cost,
                "remaining": max(0, HOUR_TOKENS - hour),
            },
            "tokensPerProjectPerHour": {
                "consumed": self.report_cost,
                "remaining": max(0, PROJECT_HOUR_TOKENS - hour),
            },
            "concurrentRequests": {"consumed": 0, "remaining": 10},
            "serverErrorsPerProjectPerHour": {"consumed": 0, "remaining": 10},
            "potentiallyThresholdedRequestsPerHour": {"consumed": 0, "remaining": 120},
        }

    def _reports(
        self, user: str, property_id: str, method: str, request: httpx.Request
    ) -> httpx.Response:
        prop = self.properties.get(property_id)
        if prop is None or user not in prop.users or prop.deleted:
            return self.failure(403, "PERMISSION_DENIED")
        body = json.loads(request.content or b"{}")
        asked = body.get("requests", []) if method == "batchRunReports" else [body]
        if method == "batchRunReports" and not 1 <= len(asked) <= 5:
            return self.failure(400, "INVALID_ARGUMENT")
        reports = []
        for one in asked:
            day = self.day_used.get(property_id, 0) + self.report_cost
            hour = self.hour_used.get(property_id, 0) + self.report_cost
            if day > DAY_TOKENS or hour > HOUR_TOKENS:
                return self.failure(429, "RESOURCE_EXHAUSTED")
            self.day_used[property_id], self.hour_used[property_id] = day, hour
            report = self.report_handler(self, property_id, one)
            if one.get("returnPropertyQuota"):
                report = {**report, "propertyQuota": self._quota(property_id)}
            reports.append(report)
        if method == "runReport":
            return httpx.Response(200, json=reports[0])
        return httpx.Response(
            200, json={"reports": reports, "kind": "analyticsData#batchRunReports"}
        )

    def http_factory(self) -> SafeHttpClient:
        return SafeHttpClient(
            POLICY,
            resolver=lambda host, port: [PUBLIC_IP],
            transport=httpx.MockTransport(self.handler),
        )


def build_provider(sim: GA4Sim, *, burst: int = 1000) -> GoogleAnalyticsProvider:
    """As for the other simulators: the frozen test clock never refills the per-connection
    limiter, so tests get a large burst unless they test the limit itself."""
    provider = GoogleAnalyticsProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        api_version=API_VERSION,
        http_factory=sim.http_factory,
        clock=sim.clock,
    )
    rate, _ = provider.rate_limit
    provider.rate_limit = (rate, burst)
    return provider
