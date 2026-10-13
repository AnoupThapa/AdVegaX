"""Shopify provider — connect and discovery (Phase 2A, task 2A-03; PHASE_02A_PLAN §6).

Read-only. Authorization-code grant for a standalone app with **expiring offline tokens**
(``expiring=1``): 1-hour access token, rotating 90-day refresh token. Every callback and install
request is HMAC-verified with the serving app's client secret; the shop must match the shop the
flow started with. Tokens are refreshed and rotated (2A-04) and webhooks verified (2A-05);
stores are imported through bulk exports (2A-06); incremental sync follows in 2A-07.

Facts verified against shopify.dev on 2026-10-13; anything only confirmable on a live
development store is listed under "to confirm live" in INTEGRATION_GUIDES (option C, A18).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta
from urllib.parse import urlencode

from app.core.clock import Clock
from app.providers.base.capabilities import Capability, ProviderCapabilities
from app.providers.base.errors import (
    AccountMismatchError,
    AuthExpiredError,
    InvalidConnectParamsError,
    InvalidRequestError,
    InvalidSignatureError,
    MissingScopesError,
    PermissionDeniedError,
    RetryableError,
    UnsupportedOperationError,
)
from app.providers.base.interfaces import Secrets
from app.providers.base.types import (
    AuthorizationRequest,
    AuthScheme,
    BulkKind,
    BulkOperationState,
    CommerceRecord,
    ConnectResult,
    PreparedConnect,
    ProviderCategory,
    ResourceDescriptor,
    ResourceKind,
    SyncSummary,
    WebhookDelivery,
)
from app.providers.shopify.admin_api import AdminApi, HttpFactory
from app.providers.shopify.bulk import (
    CATALOGUE_QUERY,
    RUN_MUTATION,
    STATE_QUERY,
    BulkExportRejectedError,
    ExportReader,
    orders_query,
    parse_state,
)
from app.providers.shopify.config import ShopifyApp, app_for_shop
from app.providers.shopify.shops import ShopDomainError, is_valid_shop, normalize_shop
from app.providers.shopify.signatures import verify_query
from app.providers.shopify.webhooks import parse_webhook as _parse_webhook

SHOP_PARAM = "shop_domain"

SHOP_QUERY = """
query AdVegaXShop {
  shop { id name currencyCode ianaTimezone myshopifyDomain }
}
"""


# Shopify may return implied scopes (e.g. write_x implies read_x); a granted write scope
# satisfies the matching read scope.
def _granted_covers(granted: set[str], required: str) -> bool:
    if required in granted:
        return True
    return required.startswith("read_") and f"write_{required[5:]}" in granted


class ShopifyProvider:
    code = "shopify"
    display_name = "Shopify"
    category = ProviderCategory.COMMERCE
    auth_scheme = AuthScheme.OAUTH2
    capabilities = ProviderCapabilities(
        frozenset(
            {
                Capability.APP_INSTALL,
                Capability.TOKEN_REFRESH,
                Capability.BULK_IMPORT,
                Capability.WEBHOOKS,
                Capability.PRODUCT_COST,
                Capability.INVENTORY,
                Capability.REFUND_LINES,
                Capability.PRESENTMENT_CURRENCY,
            }
        )
    )
    test_only = False
    rate_limit = (10.0, 20)  # per connection; GraphQL cost-aware limiting follows in 2A-07

    def __init__(
        self,
        *,
        apps: tuple[ShopifyApp, ...],
        http_factory: HttpFactory,
        api_version: str,
        scopes: tuple[str, ...],
        clock: Clock,
        install_max_age: timedelta,
        default_order_history: timedelta,
        download_hosts: frozenset[str] = frozenset({"storage.googleapis.com"}),
    ) -> None:
        if not apps:
            raise ValueError("at least one Shopify app must be configured")
        self._apps = apps
        self._api = AdminApi(http_factory, api_version)
        self._scopes = scopes
        self._clock = clock
        self._install_max_age = install_max_age
        self._default_order_history = default_order_history
        self._download_hosts = download_hosts
        self._http_factory = http_factory

    # ------------------------------------------------------------------ helpers
    def _app(self, shop: str) -> ShopifyApp:
        app = app_for_shop(self._apps, shop)
        if app is None:
            raise InvalidConnectParamsError()
        return app

    # ------------------------------------------------------------------ connect
    def prepare_connect(self, params: Mapping[str, str]) -> PreparedConnect:
        if set(params) - {SHOP_PARAM}:
            raise InvalidConnectParamsError()
        try:
            shop = normalize_shop(params.get(SHOP_PARAM, ""))
        except ShopDomainError:
            raise InvalidConnectParamsError() from None
        self._app(shop)  # no configured app serves this store → refuse before redirecting
        return PreparedConnect(params={SHOP_PARAM: shop}, account_id=shop)

    def authorization_url(self, request: AuthorizationRequest) -> str:
        shop = request.provider_params.get(SHOP_PARAM, "")
        if not is_valid_shop(shop):
            raise InvalidConnectParamsError()
        query = {
            "client_id": self._app(shop).client_id,
            "scope": ",".join(self._scopes),
            "redirect_uri": request.redirect_uri,
            "state": request.state,
        }
        return f"https://{shop}/admin/oauth/authorize?{urlencode(query)}"

    def complete_authorization(
        self,
        params: Mapping[str, str],
        *,
        redirect_uri: str,  # noqa: ARG002 - registered with Shopify; not resent on exchange
        code_verifier: str | None,  # noqa: ARG002 - Shopify does not use PKCE
        provider_params: Mapping[str, str],
    ) -> ConnectResult:
        expected_shop = provider_params.get(SHOP_PARAM, "")
        if not is_valid_shop(expected_shop):
            raise InvalidConnectParamsError()
        app = self._app(expected_shop)
        if not verify_query(params, app.client_secret):
            raise InvalidSignatureError()
        if params.get("shop", "").lower() != expected_shop:
            raise AccountMismatchError()
        code = params.get("code", "")
        if not code or len(code) > 512:
            raise InvalidRequestError()
        token = self._api.post_form(
            expected_shop,
            "/admin/oauth/access_token",
            {
                "client_id": app.client_id,
                "client_secret": app.client_secret,
                "code": code,
                "expiring": "1",
            },
        )
        access, refresh = token.get("access_token"), token.get("refresh_token")
        if not isinstance(access, str) or not access or not isinstance(refresh, str):
            raise InvalidRequestError()
        granted = {s.strip() for s in str(token.get("scope", "")).split(",") if s.strip()}
        if not all(_granted_covers(granted, s) for s in self._scopes):
            raise MissingScopesError()
        return ConnectResult(
            secrets={"shop": expected_shop, "access_token": access, "refresh_token": refresh},
            granted_scopes=tuple(sorted(granted)),
            account_label=expected_shop,
            token_expires_in_seconds=_positive_int(token.get("expires_in")),
            refresh_expires_in_seconds=_positive_int(token.get("refresh_token_expires_in")),
            external_account_id=expected_shop,
        )

    def verify_install(self, params: Mapping[str, str]) -> str:
        """Shopify-initiated install (install link; later the App Store): HMAC + freshness."""
        shop = params.get("shop", "").lower()
        if not is_valid_shop(shop):
            raise InvalidConnectParamsError()
        app = self._app(shop)
        if not verify_query(params, app.client_secret):
            raise InvalidSignatureError()
        try:
            issued = int(params.get("timestamp", ""))
        except ValueError:
            raise InvalidSignatureError() from None
        age = self._clock.now().timestamp() - issued
        if age < -60 or age > self._install_max_age.total_seconds():
            raise InvalidSignatureError()  # stale or from the future: possible replay
        return shop

    # ------------------------------------------------------------------ webhooks
    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookDelivery:
        """HMAC over the raw body with the serving app's secret, then metadata only (2A-05)."""
        return _parse_webhook(self._apps, headers, body)

    # ------------------------------------------------------------------ token lifecycle
    def refresh_credentials(self, secrets: Secrets) -> ConnectResult:
        """Rotate expiring offline tokens (verified 2026-10-13): ``POST
        https://{shop}/admin/oauth/access_token`` with ``grant_type=refresh_token``. Each
        refresh returns a new access token **and** a new refresh token; both must be saved."""
        shop = str(secrets.get("shop", ""))
        refresh = secrets.get("refresh_token")
        if not is_valid_shop(shop) or not isinstance(refresh, str) or not refresh:
            raise AuthExpiredError("refresh_unavailable")
        app = app_for_shop(self._apps, shop)
        if app is None:  # the serving app was removed from configuration
            raise AuthExpiredError("app_not_configured")
        try:
            token = self._api.post_form(
                shop,
                "/admin/oauth/access_token",
                {
                    "client_id": app.client_id,
                    "client_secret": app.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                },
            )
        except (InvalidRequestError, PermissionDeniedError, AuthExpiredError):
            # Shopify refused the refresh token (expired, retired by a newer token, or the app
            # was uninstalled): the person must reconnect. Retryable errors propagate.
            raise AuthExpiredError("refresh_rejected") from None
        access, new_refresh = token.get("access_token"), token.get("refresh_token")
        if not isinstance(access, str) or not access or not isinstance(new_refresh, str):
            raise AuthExpiredError("refresh_rejected")
        granted = {s.strip() for s in str(token.get("scope", "")).split(",") if s.strip()}
        return ConnectResult(
            secrets={"shop": shop, "access_token": access, "refresh_token": new_refresh},
            granted_scopes=tuple(sorted(granted)),
            account_label=shop,
            token_expires_in_seconds=_positive_int(token.get("expires_in")),
            refresh_expires_in_seconds=_positive_int(token.get("refresh_token_expires_in")),
            external_account_id=shop,
        )

    # ------------------------------------------------------------------ discovery
    def discover_resources(self, secrets: Secrets) -> list[ResourceDescriptor]:
        shop = str(secrets.get("shop", ""))
        data = self._api.graphql(shop, str(secrets.get("access_token", "")), SHOP_QUERY)
        info = data.get("shop")
        if not isinstance(info, dict) or not info.get("id"):
            raise InvalidRequestError()
        if str(info.get("myshopifyDomain", "")).lower() != shop:
            raise AccountMismatchError()
        return [
            ResourceDescriptor(
                kind=ResourceKind.STORE,
                external_id=str(info["id"]),
                display_name=_text(info.get("name")),
                currency=_text(info.get("currencyCode")),
                timezone=_text(info.get("ianaTimezone")),
            )
        ]

    def sync_resource(
        self,
        secrets: Secrets,  # noqa: ARG002 - provider contract
        resource: ResourceDescriptor,  # noqa: ARG002
    ) -> SyncSummary:
        # Stores are imported through bulk exports driven by the core (``BULK_IMPORT``).
        raise UnsupportedOperationError()

    # ------------------------------------------------------------------ bulk import (2A-06)
    def history_limit(self, granted_scopes: tuple[str, ...]) -> timedelta | None:
        """Orders older than 60 days need Shopify's approval and ``read_all_orders``."""
        return None if "read_all_orders" in granted_scopes else self._default_order_history

    @staticmethod
    def _credentials(secrets: Secrets) -> tuple[str, str]:
        shop, token = secrets.get("shop"), secrets.get("access_token")
        if not isinstance(shop, str) or not is_valid_shop(shop):
            raise AuthExpiredError("credentials_incomplete")
        if not isinstance(token, str) or not token:
            raise AuthExpiredError("credentials_incomplete")
        return shop, token

    def start_bulk_export(self, secrets: Secrets, kind: BulkKind, *, since: datetime | None) -> str:
        shop, token = self._credentials(secrets)
        query = CATALOGUE_QUERY if kind is BulkKind.CATALOGUE else orders_query(since)
        data = self._api.graphql(shop, token, RUN_MUTATION, {"query": query})
        payload = data.get("bulkOperationRunQuery")
        if not isinstance(payload, dict):
            raise RetryableError("invalid_response")
        if payload.get("userErrors"):
            # Messages are not copied (they can echo the query); the code is enough to act on.
            raise BulkExportRejectedError()
        operation = payload.get("bulkOperation")
        operation_id = operation.get("id") if isinstance(operation, dict) else None
        if not isinstance(operation_id, str) or not operation_id:
            raise RetryableError("invalid_response")
        return operation_id

    def bulk_export_state(self, secrets: Secrets, operation_id: str) -> BulkOperationState:
        shop, token = self._credentials(secrets)
        data = self._api.graphql(shop, token, STATE_QUERY, {"id": operation_id})
        return parse_state(data.get("bulkOperation"))

    def read_bulk_export(self, result_url: str, kind: BulkKind) -> Iterator[CommerceRecord]:
        """Stream the JSONL file from Shopify's storage host (allowlisted), line by line."""
        client = self._http_factory()
        try:
            lines = client.stream_lines(result_url, allowed_host=self._download_hosts.__contains__)
            yield from ExportReader(kind).records(lines)
        finally:
            client.close()

    def revoke(self, secrets: Secrets) -> None:  # noqa: ARG002 - see note below
        # No app-initiated revocation is documented for this flow (to confirm live, Step 0
        # item 6). Disconnecting deletes AdVegaX's tokens; the web app tells the person to
        # uninstall the app in Shopify as well.
        raise UnsupportedOperationError()


def _positive_int(value: object) -> int | None:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _text(value: object) -> str | None:
    return str(value)[:255] if value else None
