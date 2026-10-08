"""Provider interfaces (D4). Core domains depend only on these and normalized types.

Category-specific read/write methods are added when the first real provider of each category
is implemented (Phase 2A+) so that the contract is shaped by two real platforms, not guesses.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from app.providers.base.capabilities import ProviderCapabilities
from app.providers.base.types import (
    AuthorizationRequest,
    AuthScheme,
    ConnectResult,
    ProviderCategory,
    ResourceDescriptor,
    SyncSummary,
)

Secrets = Mapping[str, Any]


@runtime_checkable
class PlatformProvider(Protocol):
    code: str
    category: ProviderCategory
    auth_scheme: AuthScheme
    capabilities: ProviderCapabilities
    test_only: bool
    rate_limit: tuple[float, int]  # (requests per second, burst) per connection

    def authorization_url(self, request: AuthorizationRequest) -> str: ...

    def complete_authorization(
        self, params: Mapping[str, str], *, redirect_uri: str, code_verifier: str | None
    ) -> ConnectResult: ...

    def discover_resources(self, secrets: Secrets) -> list[ResourceDescriptor]: ...

    def sync_resource(self, secrets: Secrets, resource: ResourceDescriptor) -> SyncSummary: ...

    def revoke(self, secrets: Secrets) -> None: ...


class CommerceProvider(PlatformProvider, Protocol):
    """Shopify, WooCommerce, … — catalogue/order reads are added in Phase 2A/2B."""


class AdvertisingProvider(PlatformProvider, Protocol):
    """Google Ads, Meta, … — structure/performance reads in Phases 3-4; writes only via 10A."""


class AnalyticsProvider(PlatformProvider, Protocol):
    """GA4, … — aggregated reads in Phase 5."""
