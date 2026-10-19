"""Google sign-in and Google Ads REST client over the SSRF-safe HTTP client (Phase 3, 3-03).

PHASE_03_PLAN §4.1, §7 (facts verified 2026-10-15; "to confirm live" in INTEGRATION_GUIDES):

* **Fixed Google hosts only** — the sign-in token and revocation endpoints and
  ``googleads.googleapis.com``. No address ever comes from a user; redirects are not followed.
* **Read-only:** the only Google Ads methods are ``customers:listAccessibleCustomers``,
  ``googleAds:search`` and ``googleAds:searchStream`` (static guard, tests/security).
* Headers: ``Authorization: Bearer``, ``developer-token`` and, when an account is reached
  through a manager, ``login-customer-id``. Customer ids are validated (digits only) before
  they enter a path or header.
* Errors become plain codes. Response bodies, Google's messages, tokens and the developer
  token are never placed in exceptions or logs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from app.providers.base.errors import (
    AuthExpiredError,
    InvalidRequestError,
    PermissionDeniedError,
    PlatformQuotaError,
    ResourceNotFoundError,
    ResourceUnavailableError,
    RetryableError,
)
from app.providers.google.oauth import (  # shared with Google Analytics (Phase 5)
    AUTHORIZE_URL,
    REVOKE_URL,
    TOKEN_URL,
    GoogleSignIn,
    HttpFactory,
    SignInRejectedError,
    UnexpectedResponseError,
)
from app.providers.http.client import SafeResponse

__all__ = [
    "AUTHORIZE_URL",
    "REVOKE_URL",
    "TOKEN_URL",
    "GoogleSignIn",
    "HttpFactory",
    "SignInRejectedError",
    "UnexpectedResponseError",
]

ADS_BASE = "https://googleads.googleapis.com"

_CUSTOMER_ID = re.compile(r"^[0-9]{1,20}$")
MAX_PAGES = 1000  # 10,000 rows a page: a runaway answer stops at 10 million rows


# ------------------------------------------------------------------ plain error codes
class NoAccountAccessError(ResourceUnavailableError):
    code = "no_account_access"


class AccountNotEnabledError(ResourceUnavailableError):
    """Cancelled, suspended or not yet set up in Google Ads."""

    code = "account_not_enabled"


class DeveloperTokenNotApprovedError(ResourceUnavailableError):
    """AdVegaX's developer token cannot reach this account (e.g. test access only)."""

    code = "developer_token_not_approved"


class DeveloperTokenInvalidError(PermissionDeniedError):
    code = "developer_token_invalid"


class NotAdsUserError(PermissionDeniedError):
    """The Google account that signed in has no Google Ads account."""

    code = "not_ads_user"


class QuotaExhaustedError(PlatformQuotaError):
    """Google's daily or per-second allowance for AdVegaX was reached."""

    code = "quota_exhausted"


class BadQueryError(InvalidRequestError):
    code = "bad_query"


# Google Ads error values (``errorCode`` entries of a GoogleAdsFailure) → plain codes.
# The values are Google's documented enum names; which ones appear for which situation is to
# be confirmed live (Step 0 item 3). Anything unknown falls back to the HTTP status.
_ADS_ERRORS: dict[str, type[Exception]] = {
    "OAUTH_TOKEN_EXPIRED": AuthExpiredError,
    "OAUTH_TOKEN_INVALID": AuthExpiredError,
    "OAUTH_TOKEN_REVOKED": SignInRejectedError,
    "OAUTH_TOKEN_DISABLED": SignInRejectedError,
    "NOT_ADS_USER": NotAdsUserError,
    "USER_PERMISSION_DENIED": NoAccountAccessError,
    "CUSTOMER_NOT_FOUND": NoAccountAccessError,
    "CUSTOMER_NOT_ENABLED": AccountNotEnabledError,
    "DEVELOPER_TOKEN_NOT_APPROVED": DeveloperTokenNotApprovedError,
    "DEVELOPER_TOKEN_PROHIBITED": DeveloperTokenNotApprovedError,
    "DEVELOPER_TOKEN_INVALID": DeveloperTokenInvalidError,
    "RESOURCE_EXHAUSTED": QuotaExhaustedError,
    "RESOURCE_TEMPORARILY_EXHAUSTED": QuotaExhaustedError,
}


def valid_customer_id(value: str) -> str:
    text = str(value or "").replace("-", "")
    if not _CUSTOMER_ID.fullmatch(text):
        raise InvalidRequestError()
    return text


def _json(response: SafeResponse) -> Any:
    try:
        return json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        raise UnexpectedResponseError() from None


def _retry_delay(details: list[Any]) -> float | None:
    """``quotaErrorDetails.retryDelay`` (e.g. ``"30s"``) when Google gives one."""
    for detail in details:
        for error in (detail or {}).get("errors", []) if isinstance(detail, dict) else []:
            delay = ((error or {}).get("details") or {}).get("quotaErrorDetails", {})
            value = delay.get("retryDelay") if isinstance(delay, dict) else None
            if isinstance(value, str) and value.endswith("s"):
                try:
                    return max(0.0, float(value[:-1]))
                except ValueError:
                    return None
    return None


def _ads_error_values(body: Any) -> tuple[list[str], list[Any]]:
    error = body.get("error") if isinstance(body, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    details = details if isinstance(details, list) else []
    values: list[str] = []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        for item in detail.get("errors") or []:
            code = item.get("errorCode") if isinstance(item, dict) else None
            if isinstance(code, dict):
                values.extend(str(v) for v in code.values())
                if "queryError" in code:
                    values.append("QUERY_ERROR")
    return values, details


def raise_for_ads(response: SafeResponse) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    if 300 <= status < 400:
        raise UnexpectedResponseError()  # Google's API never redirects; refuse to follow
    try:
        body = json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        body = None
    values, details = _ads_error_values(body)
    for value in values:
        if value == "QUERY_ERROR":
            raise BadQueryError()
        cls = _ADS_ERRORS.get(value)
        if cls is QuotaExhaustedError:
            raise QuotaExhaustedError(retry_after_seconds=_retry_delay(details))
        if cls is not None:
            raise cls()
    if status == 401:
        raise AuthExpiredError()
    if status == 403:
        raise PermissionDeniedError()
    if status == 404:
        raise ResourceNotFoundError()
    if status == 429:
        raise QuotaExhaustedError(retry_after_seconds=_retry_delay(details))
    if status >= 500:
        raise RetryableError("server_error")
    raise InvalidRequestError()


class GoogleAdsClient:
    """Read-only Google Ads REST calls (one pinned API version, e.g. ``v25``)."""

    def __init__(self, http_factory: HttpFactory, version: str, developer_token: str) -> None:
        if not re.fullmatch(r"v[0-9]{2,3}", version):
            raise ValueError("Google Ads API version must look like v25")
        self._http_factory = http_factory
        self._version = version
        self._developer_token = developer_token

    def _headers(self, access_token: str, login_customer_id: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": self._developer_token,
            "Accept": "application/json",
        }
        if login_customer_id:
            headers["login-customer-id"] = valid_customer_id(login_customer_id)
        return headers

    def _send(
        self, method: str, path: str, headers: dict[str, str], body: Any = None
    ) -> SafeResponse:
        client = self._http_factory()
        try:
            response = client.request(
                method,
                f"{ADS_BASE}/{self._version}{path}",
                headers=headers,
                json=body,
                follow_redirects=False,
            )
        finally:
            client.close()
        raise_for_ads(response)
        return response

    def list_accessible_customers(self, access_token: str) -> list[str]:
        """Customer ids the signed-in person has **direct** access to."""
        response = self._send(
            method="GET",
            path="/customers:listAccessibleCustomers",
            headers=self._headers(access_token, None),
        )
        body = _json(response)
        names = body.get("resourceNames") if isinstance(body, dict) else None
        if names is None:
            return []
        if not isinstance(names, list):
            raise UnexpectedResponseError()
        ids = []
        for name in names:
            if not isinstance(name, str) or not name.startswith("customers/"):
                raise UnexpectedResponseError()
            ids.append(valid_customer_id(name.removeprefix("customers/")))
        return ids

    def search(
        self,
        access_token: str,
        customer_id: str,
        query: str,
        *,
        login_customer_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """GAQL ``search``: rows page by page (10,000 a page); follow-up pages are free."""
        path = f"/customers/{valid_customer_id(customer_id)}/googleAds:search"
        headers = self._headers(access_token, login_customer_id)
        token: str | None = None
        for _ in range(MAX_PAGES):
            body: dict[str, Any] = {"query": query}
            if token:
                body["pageToken"] = token
            page = _json(self._send("POST", path, headers, body))
            if not isinstance(page, dict):
                raise UnexpectedResponseError()
            rows = page.get("results") or []
            if not isinstance(rows, list):
                raise UnexpectedResponseError()
            for row in rows:
                if isinstance(row, dict):
                    yield row
            token = page.get("nextPageToken")
            if not token:
                return
            if not isinstance(token, str) or len(token) > 4096:
                raise UnexpectedResponseError()
        raise UnexpectedResponseError()

    def search_stream(
        self,
        access_token: str,
        customer_id: str,
        query: str,
        *,
        login_customer_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """GAQL ``searchStream``: the whole result in one answer (one operation)."""
        path = f"/customers/{valid_customer_id(customer_id)}/googleAds:searchStream"
        response = self._send(
            "POST", path, self._headers(access_token, login_customer_id), {"query": query}
        )
        batches = _json(response)
        if isinstance(batches, dict):  # some servers send a single batch object
            batches = [batches]
        if not isinstance(batches, list):
            raise UnexpectedResponseError()
        for batch in batches:
            rows = batch.get("results") if isinstance(batch, dict) else None
            for row in rows or []:
                if isinstance(row, dict):
                    yield row
