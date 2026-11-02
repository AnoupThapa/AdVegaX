"""WooCommerce REST API client (task 2B-03, PHASE_02B_PLAN §4.1 and §7).

* REST API ``wc/v3`` (and the public WordPress index) under ``{store}/wp-json``.
* **HTTP Basic auth over HTTPS** with the read-only consumer key and secret. The documented
  fallback that puts them in the query string is never used (Q-2B-6): URLs end up in logs.
* Every request goes through ``SafeHttpClient`` (SSRF policy and address pinning on every
  request, size and time limits) and **never follows redirects**: a merchant store must be
  addressed exactly, and credentials must never be sent anywhere else.
* Errors become provider error codes. Response bodies never enter errors or logs; only the
  WooCommerce error *code* (a fixed identifier such as ``woocommerce_rest_cannot_view``) is
  read to tell a rejected key from a host that strips the login header.

Paging follows WordPress: ``page`` / ``per_page`` and the ``X-WP-Total`` /
``X-WP-TotalPages`` response headers.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from app.providers.base.errors import (
    AuthExpiredError,
    BlockedDestinationError,
    InvalidRequestError,
    PermissionDeniedError,
    RateLimitedError,
    ResourceNotFoundError,
    RetryableError,
)
from app.providers.http.client import REDIRECT_STATUSES, SafeHttpClient, SafeResponse
from app.providers.woocommerce.stores import StoreAddress

USER_AGENT = "AdVegaX/1.0 (+read-only)"
MAX_PER_PAGE = 100
_ROUTE = re.compile(r"^/[A-Za-z0-9/_.-]{0,200}$")
_MAX_RETRY_AFTER = 300.0

# WooCommerce / WordPress error codes (fixed identifiers, to confirm live — Step 0).
_KEY_REJECTED_CODES = frozenset(
    {
        "woocommerce_rest_authentication_error",  # "Consumer key is invalid" and friends
        "woocommerce_rest_invalid_signature",
    }
)
_NO_ROUTE_CODES = frozenset({"rest_no_route"})

HttpFactory = Callable[[], SafeHttpClient]


class KeyRejectedError(AuthExpiredError):
    """The store refused the key: revoked, or the WordPress user behind it was deleted."""

    code = "key_rejected"


class AuthHeaderStrippedError(PermissionDeniedError):
    """The store saw no credentials at all: its web host removes the ``Authorization``
    header (Q-2B-6). Fixable on the host; AdVegaX never falls back to keys in URLs."""

    code = "auth_header_stripped"


class StoreRedirectedError(InvalidRequestError):
    """The address redirects (e.g. to ``www.`` or another domain): re-enter the exact one."""

    code = "store_redirected"


class WooCommerceApiNotFoundError(ResourceNotFoundError):
    """No WooCommerce REST API at this address (not WooCommerce, or REST disabled)."""

    code = "woocommerce_api_not_found"


class UnexpectedResponseError(InvalidRequestError):
    """The store answered with something that is not the API's JSON (e.g. a security
    plugin's challenge page)."""

    code = "unexpected_response"


@dataclass(frozen=True)
class WooResponse:
    data: Any  # parsed JSON: dict or list
    total: int | None = None  # X-WP-Total
    total_pages: int | None = None  # X-WP-TotalPages


class WooClient:
    def __init__(
        self,
        http_factory: HttpFactory,
        store: StoreAddress,
        *,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
    ) -> None:
        if (consumer_key is None) != (consumer_secret is None):
            raise ValueError("consumer key and secret go together")
        self._http_factory = http_factory
        self._store = store
        self._auth: str | None = None
        if consumer_key is not None and consumer_secret is not None:
            token = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
            self._auth = f"Basic {token}"

    def __repr__(self) -> str:  # never show credentials
        return f"WooClient({self._store.base_url!r})"

    # ------------------------------------------------------------------ requests
    def index(self) -> dict[str, Any]:
        """The public WordPress REST index (site name, time zone, namespaces). No credentials
        are sent: it is public, and sending the key where it is not needed only adds risk."""
        data = self._get("/", None, authenticated=False).data
        if not isinstance(data, dict):
            raise UnexpectedResponseError()
        return data

    def get(self, route: str, params: Mapping[str, str | int] | None = None) -> WooResponse:
        """``GET {store}/wp-json/wc/v3{route}`` with the store's key."""
        if self._auth is None:
            raise ValueError("this client has no credentials")
        if not route.startswith("/"):
            raise ValueError("invalid route")
        return self._get(f"/wc/v3{route}", params, authenticated=True)

    def get_page(
        self, route: str, page: int, per_page: int, params: Mapping[str, str | int] | None = None
    ) -> WooResponse:
        if page < 1 or not 1 <= per_page <= MAX_PER_PAGE:
            raise ValueError("invalid page")
        query: dict[str, str | int] = {**(params or {}), "page": page, "per_page": per_page}
        response = self.get(route, query)
        if not isinstance(response.data, list):
            raise UnexpectedResponseError()
        return response

    # ------------------------------------------------------------------ internals
    def _get(
        self, route: str, params: Mapping[str, str | int] | None, *, authenticated: bool
    ) -> WooResponse:
        if not _ROUTE.fullmatch(route) or ".." in route:
            raise ValueError("invalid route")
        url = f"{self._store.base_url}/wp-json{route}"
        if params:
            url = f"{url}?{urlencode(sorted(params.items()))}"
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if authenticated and self._auth is not None:
            headers["Authorization"] = self._auth
        client = self._http_factory()
        try:
            response = client.request("GET", url, headers=headers, follow_redirects=False)
        except BlockedDestinationError as exc:
            if str(exc) in ("too_many_redirects", "cross_host_redirect"):
                raise StoreRedirectedError() from None
            raise
        finally:
            client.close()
        return _interpret(response, authenticated=authenticated)


def _interpret(response: SafeResponse, *, authenticated: bool) -> WooResponse:
    status = response.status_code
    if status in REDIRECT_STATUSES:
        raise StoreRedirectedError()
    if status == 429:
        raise RateLimitedError(_retry_after(response.headers.get("retry-after")))
    if status >= 500 or status == 408:
        raise RetryableError("server_error")
    if status == 401:
        code = _error_code(response)
        if code in _KEY_REJECTED_CODES:
            raise KeyRejectedError()
        if authenticated:
            raise AuthHeaderStrippedError()
        raise PermissionDeniedError()
    if status == 403:
        raise PermissionDeniedError()
    if status in (404, 410):
        if _error_code(response) in _NO_ROUTE_CODES:
            raise WooCommerceApiNotFoundError()
        raise ResourceNotFoundError()
    if status >= 400:
        raise InvalidRequestError("request_refused")
    if status >= 300 or status < 200:
        raise UnexpectedResponseError()
    data = _json(response)
    if not isinstance(data, (dict, list)):
        raise UnexpectedResponseError()
    return WooResponse(
        data=data,
        total=_count(response.headers.get("x-wp-total")),
        total_pages=_count(response.headers.get("x-wp-totalpages")),
    )


def _json(response: SafeResponse) -> Any:
    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type:
        raise UnexpectedResponseError()
    try:
        return json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        raise UnexpectedResponseError() from None


def _error_code(response: SafeResponse) -> str | None:
    """The fixed WooCommerce/WordPress error identifier, if the body has one."""
    try:
        data = json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        return None
    code = data.get("code") if isinstance(data, dict) else None
    return code if isinstance(code, str) and len(code) <= 100 else None


def _count(value: str | None) -> int | None:
    if value is None or not value.isdigit() or len(value) > 12:
        return None
    return int(value)


def _retry_after(value: str | None) -> float | None:
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    if seconds is None or seconds != seconds or seconds < 0:  # NaN or negative
        return None
    return min(seconds, _MAX_RETRY_AFTER)
