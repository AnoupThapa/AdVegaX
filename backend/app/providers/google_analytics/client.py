"""Google Analytics 4 Admin and Data API client over the SSRF-safe HTTP client (Phase 5, 5-03).

PHASE_05_PLAN §4.1, §7 (facts checked 2026-10-19; "to confirm live" in INTEGRATION_GUIDES):

* **Fixed Google hosts only** — ``analyticsadmin.googleapis.com`` (discovery) and
  ``analyticsdata.googleapis.com`` (reports); the sign-in hosts are in ``providers/google``.
  No address ever comes from a user; redirects are not followed.
* **Read-only, enforced at runtime and by a static test:** every request goes through one
  ``_send`` that allows only ``GET accountSummaries``, ``GET properties/<id>``,
  ``GET properties/<id>/metadata`` and the report methods ``properties/<id>:runReport`` and
  ``:batchRunReports`` (POST, as Google defines them; they change nothing).
* The token travels in the ``Authorization`` header only; property ids are checked (digits)
  before they enter an address.
* Google's errors (``{"error": {"code", "status", "details": [{"reason"}]}}``) become plain
  codes. Google's messages, response bodies and tokens never enter exceptions or logs.
* Each report asks for the property's remaining quota (``returnPropertyQuota``); the last one
  seen is kept for pacing (task 5-06).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from app.providers.base.errors import (
    AccountBusyError,
    InvalidRequestError,
    PermissionDeniedError,
    ResourceUnavailableError,
    RetryableError,
)
from app.providers.google.oauth import HttpFactory, SignInRejectedError, UnexpectedResponseError
from app.providers.http.client import SafeResponse

ADMIN_HOST = "analyticsadmin.googleapis.com"
DATA_HOST = "analyticsdata.googleapis.com"
MAX_PAGES = 100  # 200 summaries a page: a runaway answer stops at 20,000 accounts
_PROPERTY = re.compile(r"^(?:properties/)?([0-9]{1,20})$")


# ------------------------------------------------------------------ plain error codes
class NoPropertyAccessError(ResourceUnavailableError):
    """The signed-in person cannot read this property (no access, or it was deleted)."""

    code = "no_property_access"


class AnalyticsPermissionMissingError(PermissionDeniedError):
    """The sign-in lacks ``analytics.readonly`` (the person unticked it)."""

    code = "analytics_permission_missing"


class AnalyticsApiDisabledError(PermissionDeniedError):
    """The Google Cloud project has not enabled the Analytics APIs (set-up, not the person)."""

    code = "analytics_api_disabled"


class PropertyQuotaError(AccountBusyError):
    """The property's quota for this hour or day is used up: that property waits."""

    code = "rate_limited"


class BadQueryError(InvalidRequestError):
    code = "bad_query"


@dataclass(frozen=True)
class Quota:
    """What Google says is left of the property's allowance (None = not reported)."""

    day_remaining: int | None = None
    hour_remaining: int | None = None
    project_hour_remaining: int | None = None
    concurrent_remaining: int | None = None


def valid_property_id(value: str) -> str:
    """``properties/123`` or ``123`` → ``123``; anything else never enters an address."""
    found = _PROPERTY.fullmatch(str(value or ""))
    if found is None:
        raise InvalidRequestError()
    return found.group(1)


def _json(response: SafeResponse) -> Any:
    try:
        return json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        raise UnexpectedResponseError() from None


def _remaining(block: Any) -> int | None:
    if not isinstance(block, dict):
        return None
    value = block.get("remaining")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def read_quota(body: Any) -> Quota | None:
    """``propertyQuota`` of a report answer (or of the first report of a batch)."""
    if isinstance(body, dict) and isinstance(body.get("reports"), list) and body["reports"]:
        body = body["reports"][0]
    quota = body.get("propertyQuota") if isinstance(body, dict) else None
    if not isinstance(quota, dict):
        return None
    return Quota(
        day_remaining=_remaining(quota.get("tokensPerDay")),
        hour_remaining=_remaining(quota.get("tokensPerHour")),
        project_hour_remaining=_remaining(quota.get("tokensPerProjectPerHour")),
        concurrent_remaining=_remaining(quota.get("concurrentRequests")),
    )


def _reasons(error: dict[str, Any]) -> set[str]:
    found = set()
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and isinstance(detail.get("reason"), str):
            found.add(detail["reason"])
    return found


def raise_for_google(response: SafeResponse) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    if 300 <= status < 400:
        raise UnexpectedResponseError()  # Google's APIs never redirect; refuse to follow
    try:
        body = json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    error = error if isinstance(error, dict) else {}
    reasons = _reasons(error)
    state = error.get("status") if isinstance(error.get("status"), str) else ""
    if status == 401 or state == "UNAUTHENTICATED":
        raise SignInRejectedError()
    if "SERVICE_DISABLED" in reasons or "accessNotConfigured" in reasons:
        raise AnalyticsApiDisabledError()
    if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in reasons:
        raise AnalyticsPermissionMissingError()
    if status == 429 or state == "RESOURCE_EXHAUSTED":
        raise PropertyQuotaError()
    if status in (403, 404) or state in ("PERMISSION_DENIED", "NOT_FOUND"):
        raise NoPropertyAccessError()
    if status == 400 or state == "INVALID_ARGUMENT":
        raise BadQueryError()
    if status >= 500:
        raise RetryableError("server_error")
    raise InvalidRequestError()


def _allowed(host: str, method: str, path: str, version: str) -> bool:
    """Read-only guard: the discovery reads and the report methods, nothing else."""
    prefix = f"/{version}/"
    if not path.startswith(prefix):
        return False
    rest = path[len(prefix) :]
    if host == ADMIN_HOST:
        if method != "GET":
            return False
        return rest == "accountSummaries" or bool(re.fullmatch(r"properties/[0-9]{1,20}", rest))
    if host == DATA_HOST:
        if method == "GET":
            return bool(re.fullmatch(r"properties/[0-9]{1,20}/metadata", rest))
        if method == "POST":
            return bool(re.fullmatch(r"properties/[0-9]{1,20}:(runReport|batchRunReports)", rest))
    return False


class GoogleAnalyticsClient:
    """Admin and Data API calls for one pinned version (``v1beta``)."""

    def __init__(self, http_factory: HttpFactory, version: str) -> None:
        if not re.fullmatch(r"v1(beta)?", version):
            raise ValueError("Google Analytics API version must be v1beta or v1")
        self._http_factory = http_factory
        self.version = version
        self.last_quota: Quota | None = None

    def _send(
        self,
        method: str,
        host: str,
        path: str,
        *,
        token: str,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not _allowed(host, method, path, self.version):
            raise ValueError(f"refused Google Analytics call: {method} {host}{path}")
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        url = f"https://{host}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        client = self._http_factory()
        try:
            response = client.request(
                method, url, headers=headers, json=body, follow_redirects=False
            )
        finally:
            client.close()
        raise_for_google(response)
        answer = _json(response)
        if not isinstance(answer, dict):
            raise UnexpectedResponseError()
        return answer

    # ------------------------------------------------------------------ Admin API
    def account_summaries(self, token: str) -> Iterator[dict[str, Any]]:
        """Every Analytics account the person can reach with its property summaries,
        following ``nextPageToken``."""
        params = {"pageSize": "200"}
        for _ in range(MAX_PAGES):
            page = self._send(
                method="GET",
                host=ADMIN_HOST,
                path=f"/{self.version}/accountSummaries",
                token=token,
                params=params,
            )
            rows = page.get("accountSummaries", [])
            if not isinstance(rows, list):
                raise UnexpectedResponseError()
            for row in rows:
                if isinstance(row, dict):
                    yield row
            following = page.get("nextPageToken")
            if not isinstance(following, str) or not following or len(following) > 2048:
                return
            params = {**params, "pageToken": following}
        raise UnexpectedResponseError()  # Google kept answering "more": stop rather than loop

    def get_property(self, token: str, property_id: str) -> dict[str, Any]:
        pid = valid_property_id(property_id)
        return self._send(
            method="GET",
            host=ADMIN_HOST,
            path=f"/{self.version}/properties/{pid}",
            token=token,
        )

    # ------------------------------------------------------------------ Data API
    def batch_run_reports(
        self, token: str, property_id: str, requests: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Up to 5 reports in one call; each asks for the property's remaining quota."""
        if not 1 <= len(requests) <= 5:
            raise ValueError("batchRunReports takes 1 to 5 reports")
        pid = valid_property_id(property_id)
        body = {"requests": [{**r, "returnPropertyQuota": True} for r in requests]}
        answer = self._send(
            method="POST",
            host=DATA_HOST,
            path=f"/{self.version}/properties/{pid}:batchRunReports",
            token=token,
            body=body,
        )
        self.last_quota = read_quota(answer) or self.last_quota
        reports = answer.get("reports")
        if not isinstance(reports, list) or len(reports) != len(requests):
            raise UnexpectedResponseError()
        if not all(isinstance(r, dict) for r in reports):
            raise UnexpectedResponseError()
        return reports

    def run_report(self, token: str, property_id: str, request: dict[str, Any]) -> dict[str, Any]:
        pid = valid_property_id(property_id)
        answer = self._send(
            method="POST",
            host=DATA_HOST,
            path=f"/{self.version}/properties/{pid}:runReport",
            token=token,
            body={**request, "returnPropertyQuota": True},
        )
        self.last_quota = read_quota(answer) or self.last_quota
        return answer
