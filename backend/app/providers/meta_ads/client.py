"""Meta sign-in and Graph API client over the SSRF-safe HTTP client (Phase 4, task 4-02).

PHASE_04_PLAN §4.1, §6, §7 (facts checked 2026-10-18; "to confirm live" in INTEGRATION_GUIDES):

* **Fixed Meta host only** — ``graph.facebook.com``; the browser alone opens the login dialog
  on ``www.facebook.com``. No address ever comes from a user; redirects are not followed.
* **Read-only, enforced at runtime and by a static test:** every request goes through one
  ``_send`` that refuses anything but ``GET``, except three documented writes that change
  nothing in an ad account — the token exchange (``POST /oauth/access_token``), starting an
  insights report (``POST /<object>/insights``, task 4-05) and removing AdVegaX's own
  permission on disconnect (``DELETE /me/permissions``).
* **Secrets stay out of URLs:** the access token travels in the ``Authorization`` header; the
  app secret only in the form body of the token exchange. Every call carries
  ``appsecret_proof`` (HMAC-SHA256 of the token with the app secret), so a token alone cannot
  be used against AdVegaX's app.
* Meta's errors (``{"error": {"code", "error_subcode", …}}``) become plain codes. Meta's
  messages, response bodies, tokens and the app secret never enter exceptions or logs.
* Usage headers (``x-fb-ads-insights-throttle``, ``x-business-use-case-usage``,
  ``x-app-usage``) are read on every answer; the highest percentage and Meta's own "regain
  access" estimate are kept for pacing (task 4-06).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from app.providers.base.errors import (
    AccountBusyError,
    AuthExpiredError,
    InvalidRequestError,
    PermissionDeniedError,
    PlatformQuotaError,
    RateLimitedError,
    ResourceNotFoundError,
    ResourceUnavailableError,
    RetryableError,
)
from app.providers.http.client import SafeHttpClient, SafeResponse

HttpFactory = Callable[[], SafeHttpClient]

GRAPH_BASE = "https://graph.facebook.com"
LOGIN_DIALOG = "https://www.facebook.com/{version}/dialog/oauth"  # opened by the browser only
MAX_PAGES = 500  # with ``limit`` up to 500 rows a page: a runaway answer stops at 250,000
_PATH = re.compile(r"^/[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+){0,3}$")
_NODE = re.compile(r"^(?:act_)?[0-9]{1,25}$")


# ------------------------------------------------------------------ plain error codes
class MetaSignInRejectedError(AuthExpiredError):
    """Meta no longer accepts the token: expired, removed by the person, password changed."""

    code = "meta_sign_in_rejected"


class MetaPermissionMissingError(PermissionDeniedError):
    """The token lacks a permission AdVegaX needs (e.g. ``ads_read`` was not granted)."""

    code = "meta_permission_missing"


class NoAccountAccessError(ResourceUnavailableError):
    code = "no_account_access"


class MetaRateLimitedError(AccountBusyError):
    """Meta's per-ad-account or business use-case limit (17, 613, 80000-80014, or the usage
    headers near 100 %): that account waits; retrying early extends the block."""

    code = "rate_limited"


class MetaAppLimitError(PlatformQuotaError):
    """Meta's limit for AdVegaX's whole app (error 4; subcode 1504022 is global load):
    every Meta account waits."""

    code = "rate_limited"


class TooMuchDataError(InvalidRequestError):
    """Error 100 / 1487534: the request asks for too much data at once (narrow it, or use an
    asynchronous report, task 4-05)."""

    code = "too_much_data"


class BadQueryError(InvalidRequestError):
    code = "bad_query"


class UnexpectedResponseError(RetryableError):
    code = "unexpected_response"


class ReportFailedError(RetryableError):
    """Meta could not finish an asynchronous report ("Job Failed" / "Job Skipped")."""

    code = "report_failed"


class ReportPendingError(RetryableError):
    """An asynchronous report was not finished in time; the next attempt starts a new one."""

    code = "report_pending"


# Meta's documented error codes (Graph API "Handling errors"; to confirm live, Step 0 item 4).
_APP_RATE_CODES = frozenset({4})
_RATE_CODES = frozenset({17, 32, 613, *range(80000, 80015)})
_AUTH_CODES = frozenset({102, 190, 463, 467})
_PERMISSION_CODES = frozenset({10, *range(200, 300)})
_TOO_MUCH_DATA = 1487534
_NO_OBJECT_SUBCODE = 33  # "object does not exist, or no permission to read it"


@dataclass(frozen=True)
class Usage:
    """The highest share of a Meta limit used (0-100) and Meta's wait estimate, if any.
    ``app_percent`` is AdVegaX's whole app (shared by every customer); ``account_percent``
    the ad account or business use case the answer was about."""

    percent: float = 0.0
    regain_seconds: float | None = None
    access_tier: str | None = None
    app_percent: float = 0.0
    account_percent: float = 0.0


def appsecret_proof(app_secret: str, token: str) -> str:
    return hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def valid_node(value: str) -> str:
    """An ad account (``act_123``) or object id; anything else never enters a path."""
    text = str(value or "")
    if not _NODE.fullmatch(text):
        raise InvalidRequestError()
    return text


def _json(response: SafeResponse) -> Any:
    try:
        return json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        raise UnexpectedResponseError() from None


def _header_json(headers: Mapping[str, str], name: str) -> Any:
    raw = headers.get(name)
    if not raw or len(raw) > 16_384:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value >= 0 else None


def read_usage(headers: Mapping[str, str]) -> Usage:
    """The highest percentages in Meta's usage headers (app and account), and the longest
    wait Meta names."""
    app_used: list[float] = []
    account_used: list[float] = []
    waits: list[float] = []
    tier: str | None = None
    insights = _header_json(headers, "x-fb-ads-insights-throttle")
    if isinstance(insights, dict):
        for key, bucket in (("app_id_util_pct", app_used), ("acc_id_util_pct", account_used)):
            if (n := _number(insights.get(key))) is not None:
                bucket.append(n)
        if isinstance(insights.get("ads_api_access_tier"), str):
            tier = insights["ads_api_access_tier"]
    app = _header_json(headers, "x-app-usage")
    if isinstance(app, dict):
        for key in ("call_count", "total_cputime", "total_time"):
            if (n := _number(app.get(key))) is not None:
                app_used.append(n)
    business = _header_json(headers, "x-business-use-case-usage")
    if isinstance(business, dict):
        for entries in business.values():
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict):
                    continue
                for key in ("call_count", "total_cputime", "total_time"):
                    if (n := _number(entry.get(key))) is not None:
                        account_used.append(n)
                minutes = _number(entry.get("estimated_time_to_regain_access"))
                if minutes:
                    waits.append(minutes * 60)
                if isinstance(entry.get("ads_api_access_tier"), str):
                    tier = entry["ads_api_access_tier"]
    app_percent = min(100.0, max(app_used, default=0.0))
    account_percent = min(100.0, max(account_used, default=0.0))
    return Usage(
        percent=max(app_percent, account_percent),
        regain_seconds=max(waits) if waits else None,
        access_tier=tier[:32] if tier else None,
        app_percent=app_percent,
        account_percent=account_percent,
    )


def raise_for_meta(response: SafeResponse) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    if 300 <= status < 400:
        raise UnexpectedResponseError()  # the Graph API never redirects; refuse to follow
    try:
        body = json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    subcode = error.get("error_subcode") if isinstance(error, dict) else None
    if isinstance(code, int) and not isinstance(code, bool):
        if code in _APP_RATE_CODES:
            raise MetaAppLimitError(retry_after_seconds=read_usage(response.headers).regain_seconds)
        if code in _RATE_CODES:
            usage = read_usage(response.headers)
            raise MetaRateLimitedError(retry_after_seconds=usage.regain_seconds)
        if code in _AUTH_CODES:
            raise MetaSignInRejectedError()
        if code in _PERMISSION_CODES:
            raise MetaPermissionMissingError()
        if code == 100 and subcode == _TOO_MUCH_DATA:
            raise TooMuchDataError()
        if code == 100 and subcode == _NO_OBJECT_SUBCODE:
            raise NoAccountAccessError()
        if code == 100:
            raise BadQueryError()
        if code in (1, 2):
            raise RetryableError("server_error")
    if status == 401:
        raise MetaSignInRejectedError()
    if status == 403:
        raise MetaPermissionMissingError()
    if status == 404:
        raise ResourceNotFoundError()
    if status == 429:
        raise MetaRateLimitedError()
    if status >= 500:
        raise RetryableError("server_error")
    raise InvalidRequestError()


def _allowed(method: str, path: str) -> bool:
    """Read-only guard: GET anything; the three documented writes above, nothing else."""
    if method == "GET":
        return True
    if method == "POST":
        if path == "/oauth/access_token":
            return True
        parts = path.split("/")
        return len(parts) == 3 and bool(_NODE.fullmatch(parts[1])) and parts[2] == "insights"
    return method == "DELETE" and path == "/me/permissions"


# Pacing (Q-4-12): from SLOW_ABOVE % of a limit each call waits a little longer (up to
# SLOW_MAX_SECONDS at PAUSE_AT %); from PAUSE_AT %, or while Meta names a wait, the account
# (or, for the app's own limit, every account) pauses instead of calling.
SLOW_ABOVE = 75.0
PAUSE_AT = 95.0
SLOW_MAX_SECONDS = 10.0
PAUSE_SECONDS = 600.0  # when Meta gives no estimate
_ACCOUNT_IN_PATH = re.compile(r"^/(act_[0-9]{1,25})(?:/|$)")


class MetaGraphClient:
    """Graph API calls for one pinned version (e.g. ``v26.0``).

    Usage is remembered per process: AdVegaX's app as a whole, and each ad account it has
    read. Every Meta answer carries fresh figures, so a worker learns them on its first call.
    """

    def __init__(
        self,
        http_factory: HttpFactory,
        version: str,
        app_secret: str,
        *,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not re.fullmatch(r"v[0-9]{2,3}\.0", version):
            raise ValueError("Meta API version must look like v26.0")
        self._http_factory = http_factory
        self.version = version
        self._app_secret = app_secret
        self._now = now or time.time
        self._sleep = sleep or time.sleep
        self.last_usage = Usage()
        self._app_percent = 0.0
        self._account_percent: dict[str, float] = {}
        self._app_paused_until = 0.0
        self._paused_until: dict[str, float] = {}

    # ------------------------------------------------------------------ pacing
    def _pace(self, account: str | None) -> None:
        now = self._now()
        if self._app_paused_until > now:
            raise MetaAppLimitError(retry_after_seconds=self._app_paused_until - now)
        if account is not None and self._paused_until.get(account, 0.0) > now:
            raise MetaRateLimitedError(retry_after_seconds=self._paused_until[account] - now)
        used = max(self._app_percent, self._account_percent.get(account or "", 0.0))
        if used >= SLOW_ABOVE:
            share = min(1.0, (used - SLOW_ABOVE) / (PAUSE_AT - SLOW_ABOVE))
            self._sleep(round(max(1.0, SLOW_MAX_SECONDS * share), 1))

    def _learn(self, usage: Usage, account: str | None, *, refused: bool = False) -> None:
        """Remember the usage of this answer; pause the app or the account when Meta is at
        its limit or names a wait (``refused``: Meta already turned the call down)."""
        now = self._now()
        wait = usage.regain_seconds or PAUSE_SECONDS
        self._app_percent = usage.app_percent
        if usage.app_percent >= PAUSE_AT:
            self._app_paused_until = max(self._app_paused_until, now + wait)
        if account is not None:
            self._account_percent[account] = usage.account_percent
            if usage.account_percent >= PAUSE_AT or (usage.regain_seconds and not refused):
                self._paused_until[account] = max(self._paused_until.get(account, 0.0), now + wait)

    def _refused(self, exc: RateLimitedError, account: str | None) -> None:
        now = self._now()
        wait = exc.retry_after_seconds or PAUSE_SECONDS
        if isinstance(exc, MetaAppLimitError):
            self._app_paused_until = max(self._app_paused_until, now + wait)
        elif account is not None:
            self._paused_until[account] = max(self._paused_until.get(account, 0.0), now + wait)
        exc.retry_after_seconds = wait

    def _send(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        params: Mapping[str, str] | None = None,
        form: dict[str, str] | None = None,
    ) -> Any:
        if not _PATH.fullmatch(path) or not _allowed(method, path):
            raise ValueError(f"refused Meta call: {method} {path}")  # programming error
        query = dict(params or {})
        headers = {"Accept": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
            query["appsecret_proof"] = appsecret_proof(self._app_secret, token)
        url = f"{GRAPH_BASE}/{self.version}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        found = _ACCOUNT_IN_PATH.match(path)
        account = found.group(1) if found else None
        if token is not None:
            self._pace(account)
        client = self._http_factory()
        try:
            response = client.request(
                method, url, headers=headers, data=form, follow_redirects=False
            )
        finally:
            client.close()
        self.last_usage = read_usage(response.headers)
        try:
            raise_for_meta(response)
        except RateLimitedError as exc:
            self._learn(self.last_usage, account, refused=True)
            self._refused(exc, account)
            raise
        self._learn(self.last_usage, account)
        return _json(response)

    def get(self, token: str, path: str, params: Mapping[str, str] | None = None) -> Any:
        body = self._send(method="GET", path=path, token=token, params=params)
        if not isinstance(body, dict):
            raise UnexpectedResponseError()
        return body

    def get_all(
        self, token: str, path: str, params: Mapping[str, str] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Every row of a list edge, following Meta's ``after`` cursor (never its ``next`` URL,
        which repeats the token in the address)."""
        query = dict(params or {})
        for _ in range(MAX_PAGES):
            page = self.get(token, path, query)
            rows = page.get("data")
            if not isinstance(rows, list):
                raise UnexpectedResponseError()
            for row in rows:
                if isinstance(row, dict):
                    yield row
            paging = page.get("paging")
            after = None
            if isinstance(paging, dict) and paging.get("next"):
                cursors = paging.get("cursors")
                after = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(after, str) or not after or len(after) > 2048:
                return
            query["after"] = after
        raise UnexpectedResponseError()  # Meta kept answering "more": stop rather than loop

    def exchange(self, form: dict[str, str]) -> dict[str, Any]:
        """``POST /oauth/access_token`` (code or long-lived exchange). A refused grant (error
        100 or 190 on this endpoint) means the code or token is not usable."""
        try:
            body = self._send(method="POST", path="/oauth/access_token", form=form)
        except (BadQueryError, InvalidRequestError, MetaPermissionMissingError):
            raise MetaSignInRejectedError() from None
        if not isinstance(body, dict):
            raise UnexpectedResponseError()
        return body

    def start_report(self, token: str, node: str, form: dict[str, str]) -> str:
        """Start an asynchronous insights report (``POST /<node>/insights``; it changes
        nothing in the account). Returns Meta's report id."""
        body = self._send(
            method="POST", path=f"/{valid_node(node)}/insights", token=token, form=form
        )
        report = body.get("report_run_id") if isinstance(body, dict) else None
        if isinstance(report, int) and not isinstance(report, bool):
            report = str(report)
        if not isinstance(report, str) or not report.isdigit() or len(report) > 25:
            raise UnexpectedResponseError()
        return report

    def remove_permissions(self, token: str) -> None:
        """Disconnect: ``DELETE /me/permissions`` ends AdVegaX's access for this person. A token
        Meta no longer accepts counts as removed."""
        try:
            self._send(method="DELETE", path="/me/permissions", token=token)
        except MetaSignInRejectedError:
            return
