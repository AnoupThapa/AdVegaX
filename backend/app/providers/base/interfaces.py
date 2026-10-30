"""Provider interfaces (D4). Core domains depend only on these and normalized types.

Category-specific read/write methods are added when the first real provider of each category
is implemented (Phase 2A+) so that the contract is shaped by two real platforms, not guesses.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import date, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from app.providers.base.capabilities import ProviderCapabilities
from app.providers.base.types import (
    AdAccountRef,
    AdAccountState,
    AdLevel,
    AdPerformanceRecord,
    AdStructureRecord,
    AnalyticsDailyRecord,
    AnalyticsPropertyRef,
    AnalyticsPropertyState,
    AuthorizationRequest,
    AuthScheme,
    BulkKind,
    BulkOperationState,
    CommercePage,
    CommerceRecord,
    ConnectResult,
    FetchResult,
    PreparedConnect,
    ProviderCategory,
    ResourceDescriptor,
    SyncSummary,
    WebhookDelivery,
    WebhookTarget,
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
    """Shopify, WooCommerce, … The provider owns the platform's query language and mapping;
    the core receives only normalized ``Commerce*Record``s. How history is read depends on the
    platform: bulk exports (``BulkExportProvider``) or pages (``PagedImportProvider``)."""

    def history_limit(self, granted_scopes: tuple[str, ...]) -> timedelta | None:
        """How far back order history may be read with these permissions (None = no limit)."""
        ...

    def webhook_target(self, topic: str) -> WebhookTarget:
        """What an "object changed" topic refers to (2A-07)."""
        ...

    def fetch_product(self, secrets: Secrets, external_id: str) -> FetchResult: ...

    def fetch_order(self, secrets: Secrets, external_id: str) -> FetchResult: ...


@runtime_checkable
class BulkExportProvider(CommerceProvider, Protocol):
    """History through platform bulk exports (``Capability.BULK_IMPORT``, e.g. Shopify)."""

    def start_bulk_export(
        self,
        secrets: Secrets,
        kind: BulkKind,
        *,
        created_since: datetime | None = None,
        updated_since: datetime | None = None,
    ) -> str:
        """Start a bulk export, optionally filtered by creation / update time; return the
        platform's operation id."""
        ...

    def bulk_export_state(self, secrets: Secrets, operation_id: str) -> BulkOperationState: ...

    def read_bulk_export(self, result_url: str, kind: BulkKind) -> Iterator[CommerceRecord]:
        """Stream the finished export as normalized records (bounded memory)."""
        ...


@runtime_checkable
class PagedImportProvider(CommerceProvider, Protocol):
    """History read page by page (``Capability.PAGED_IMPORT``, e.g. WooCommerce, 2B-02).

    The core asks for one page per job step and keeps ``cursor`` between steps; the cursor's
    content is the provider's business (it may span several endpoints, e.g. orders then
    refunds). Filters have the same meaning as for bulk exports."""

    def read_page(
        self,
        secrets: Secrets,
        kind: BulkKind,
        cursor: str | None,
        *,
        created_since: datetime | None = None,
        updated_since: datetime | None = None,
    ) -> CommercePage: ...


class AdvertisingProvider(PlatformProvider, Protocol):
    """Google Ads, Meta, … — read-only in Phases 3-4; any change goes only through the Action
    Engine (10A). Ad accounts are discovered with ``discover_resources`` (kind ``ad_account``);
    the methods below read one linked account, reached through its ``AdAccountRef``.

    Optional attributes for a platform allowance shared by every customer (3-07):
    ``shared_daily_operations`` (operations per sliding day; None = no shared allowance),
    ``structure_operations`` (cost of ``read_account`` + ``read_structure``) and
    ``level_operations`` (cost of one ``read_performance`` call)."""

    def read_account(self, secrets: Secrets, account: AdAccountRef) -> AdAccountState:
        """The account's current name, currency, time zone and platform status."""
        ...

    def read_structure(
        self, secrets: Secrets, account: AdAccountRef
    ) -> Iterator[AdStructureRecord]:
        """Every budget, campaign, ad group and ad, removed ones included (history is kept).
        Parents come before their children."""
        ...

    def read_performance(
        self,
        secrets: Secrets,
        account: AdAccountRef,
        level: AdLevel,
        first_day: date,
        last_day: date,
    ) -> Iterator[AdPerformanceRecord]:
        """Daily figures for ``level`` between two days (inclusive, account time zone).
        Days and entities without activity may be absent: the caller writes real zeros for
        the days it asked for, so a correction that removes activity is never left stale."""
        ...


class AnalyticsProvider(PlatformProvider, Protocol):
    """GA4, … — aggregated, read-only reads (Phase 5, decision Q11). Properties are discovered
    with ``discover_resources`` (kind ``analytics_property``); the methods below read one
    linked property, reached through its ``AnalyticsPropertyRef``. Nothing here changes
    anything at the platform.

    Optional method: ``quota_left(prop) -> AnalyticsQuotaLeft | None`` — what the platform
    said is left of the property's allowance after the last read (None = nothing to watch);
    the core paces a property's run from it (Q-5-7)."""

    def read_property(self, secrets: Secrets, prop: AnalyticsPropertyRef) -> AnalyticsPropertyState:
        """The property's current name, currency, time zone and platform status."""
        ...

    def read_daily(
        self,
        secrets: Secrets,
        prop: AnalyticsPropertyRef,
        first_day: date,
        last_day: date,
    ) -> Iterator[AnalyticsDailyRecord]:
        """Daily figures in every view (total, channel, source) between two days (inclusive,
        property time zone). Days without activity may be absent: the caller writes real
        zeros at the total level for the days it asked for."""
        ...
