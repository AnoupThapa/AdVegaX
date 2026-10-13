"""Minimal Shopify Admin API client over the SSRF-safe HTTP client (A11, PHASE_02A_PLAN §6, §9).

* GraphQL Admin API only, pinned version (``SHOPIFY_API_VERSION``, 2026-10).
* Every request goes to a **validated** ``*.myshopify.com`` host through ``SafeHttpClient``.
* Errors are normalized to provider error codes. Response bodies, tokens and Shopify's error
  messages are never placed in exceptions or logs (they can echo request data).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.providers.base.errors import (
    AuthExpiredError,
    InvalidRequestError,
    PermissionDeniedError,
    RateLimitedError,
    ResourceNotFoundError,
    RetryableError,
)
from app.providers.http.client import SafeHttpClient, SafeResponse
from app.providers.shopify.shops import ShopDomainError, normalize_shop

HttpFactory = Callable[[], SafeHttpClient]


class GraphQLError(InvalidRequestError):
    code = "graphql_error"


def _retry_after(response: SafeResponse) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None


def raise_for_status(response: SafeResponse) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    if status == 401:
        raise AuthExpiredError()
    if status in (402, 403, 423):  # 402: store frozen/unpaid; 423: store locked
        raise PermissionDeniedError()
    if status == 404:
        raise ResourceNotFoundError()
    if status == 429:
        raise RateLimitedError(retry_after_seconds=_retry_after(response))
    if status >= 500:
        raise RetryableError("server_error")
    raise InvalidRequestError()


def parse_json(response: SafeResponse) -> dict[str, Any]:
    try:
        data = json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        raise RetryableError("invalid_response") from None
    if not isinstance(data, dict):
        raise RetryableError("invalid_response")
    return data


class AdminApi:
    def __init__(self, http_factory: HttpFactory, api_version: str) -> None:
        self._http_factory = http_factory
        self._version = api_version

    @staticmethod
    def _shop(shop: str) -> str:
        try:
            return normalize_shop(shop)
        except ShopDomainError:
            raise InvalidRequestError() from None

    def post_form(self, shop: str, path: str, data: dict[str, str]) -> dict[str, Any]:
        """POST ``application/x-www-form-urlencoded`` (OAuth token endpoint)."""
        url = f"https://{self._shop(shop)}{path}"
        client = self._http_factory()
        try:
            response = client.request(
                "POST", url, data=data, headers={"Accept": "application/json"}
            )
        finally:
            client.close()
        raise_for_status(response)
        return parse_json(response)

    def graphql(
        self,
        shop: str,
        access_token: str,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"https://{self._shop(shop)}/admin/api/{self._version}/graphql.json"
        client = self._http_factory()
        try:
            response = client.request(
                "POST",
                url,
                json={"query": query, "variables": variables or {}},
                headers={"X-Shopify-Access-Token": access_token, "Accept": "application/json"},
            )
        finally:
            client.close()
        raise_for_status(response)
        body = parse_json(response)
        errors = body.get("errors")
        if errors:
            codes = {
                str((e.get("extensions") or {}).get("code", ""))
                for e in errors
                if isinstance(e, dict)
            }
            if "THROTTLED" in codes:
                raise RateLimitedError(retry_after_seconds=1.0)
            if "ACCESS_DENIED" in codes:
                raise PermissionDeniedError()
            raise GraphQLError()
        data = body.get("data")
        if not isinstance(data, dict):
            raise RetryableError("invalid_response")
        return data
