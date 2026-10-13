"""Provider interfaces (D4). Core domains depend only on these and normalized types.

Category-specific read/write methods are added when the first real provider of each category
is implemented (Phase 2A+) so that the contract is shaped by two real platforms, not guesses.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from app.providers.base.capabilities import ProviderCapabilities
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
    SyncSummary,
    WebhookDelivery,
)

Secrets = Mapping[str, Any]


@runtime_checkable
class PlatformProvider(Protocol):
    code: str
    display_name: str  # human-readable label shown in the web app (PHASE_01C_PLAN §6)
    category: ProviderCategory
    auth_scheme: AuthScheme
    capabilities: ProviderCapabilities
    test_only: bool
    rate_limit: tuple[float, int]  # (requests per second, burst) per connection

    def prepare_connect(self, params: Mapping[str, str]) -> PreparedConnect:
        """Validate connect parameters from the web app; raise ``InvalidRequestError`` if bad."""
        ...

    def authorization_url(self, request: AuthorizationRequest) -> str: ...

    def complete_authorization(
        self,
        params: Mapping[str, str],
        *,
        redirect_uri: str,
        code_verifier: str | None,
        provider_params: Mapping[str, str],
    ) -> ConnectResult: ...

    def verify_install(self, params: Mapping[str, str]) -> str:
        """Verify a platform-initiated install request; return its account id.

        Only providers declaring ``Capability.APP_INSTALL`` support this; others raise.
        """
        ...

    def discover_resources(self, secrets: Secrets) -> list[ResourceDescriptor]: ...

    def sync_resource(self, secrets: Secrets, resource: ResourceDescriptor) -> SyncSummary: ...

    def revoke(self, secrets: Secrets) -> None: ...

    def refresh_credentials(self, secrets: Secrets) -> ConnectResult:
        """Exchange the refresh token for new credentials (``Capability.TOKEN_REFRESH``).

        Raises ``AuthExpiredError`` when the refresh token is no longer valid (the person must
        reconnect) and a retryable error for temporary failures.
        """
        ...

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookDelivery:
        """Verify a webhook's signature over the **raw** body, then return its metadata
        (``Capability.WEBHOOKS``). ``headers`` keys are lower-case.

        Raises ``InvalidSignatureError`` when the signature is missing or wrong (the caller
        answers 401 and stores nothing) and ``InvalidRequestError`` for a signed but malformed
        delivery. Never returns or logs the payload.
        """
        ...


@runtime_checkable
class CommerceProvider(PlatformProvider, Protocol):
    """Shopify, WooCommerce, … (``Capability.BULK_IMPORT``). The provider owns the platform's
    query language and mapping; the core receives only normalized ``Commerce*Record``s."""

    def history_limit(self, granted_scopes: tuple[str, ...]) -> timedelta | None:
        """How far back order history may be read with these permissions (None = no limit)."""
        ...

    def start_bulk_export(self, secrets: Secrets, kind: BulkKind, *, since: datetime | None) -> str:
        """Start a bulk export; return the platform's operation id."""
        ...

    def bulk_export_state(self, secrets: Secrets, operation_id: str) -> BulkOperationState: ...

    def read_bulk_export(self, result_url: str, kind: BulkKind) -> Iterator[CommerceRecord]:
        """Stream the finished export as normalized records (bounded memory)."""
        ...


class AdvertisingProvider(PlatformProvider, Protocol):
    """Google Ads, Meta, … — structure/performance reads in Phases 3-4; writes only via 10A."""


class AnalyticsProvider(PlatformProvider, Protocol):
    """GA4, … — aggregated reads in Phase 5."""
