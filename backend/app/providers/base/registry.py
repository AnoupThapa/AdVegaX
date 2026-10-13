"""Provider registry: code → implementation. Test-only providers never load when deployed."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.clock import Clock, SystemClock
from app.core.errors import NotFound
from app.core.settings import Settings
from app.providers.base.interfaces import PlatformProvider

if TYPE_CHECKING:
    from app.providers.http.client import OutboundPolicy


class UnknownProvider(NotFound):
    code = "UNKNOWN_PROVIDER"
    message = "This platform is not available."


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._providers: dict[str, PlatformProvider] = {}

    def register(self, provider: PlatformProvider) -> None:
        if provider.test_only and self._settings.is_deployed:
            raise RuntimeError(f"test-only provider '{provider.code}' cannot run when deployed")
        if provider.code in self._providers:
            raise ValueError(f"provider '{provider.code}' is already registered")
        self._providers[provider.code] = provider

    def get(self, code: str) -> PlatformProvider:
        provider = self._providers.get(code)
        if provider is None:
            raise UnknownProvider()
        return provider

    def codes(self) -> list[str]:
        return sorted(self._providers)

    def all(self) -> list[PlatformProvider]:
        """Registered providers, ordered by code."""
        return [self._providers[code] for code in self.codes()]


def build_registry(
    settings: Settings, *, clock: Clock | None = None, outbound: OutboundPolicy | None = None
) -> ProviderRegistry:
    registry = ProviderRegistry(settings)
    if not settings.is_deployed:
        from app.providers.fake.provider import FakeProvider

        registry.register(FakeProvider())
    if settings.SHOPIFY_APPS is not None and outbound is not None:
        registry.register(build_shopify(settings, clock or SystemClock(), outbound))
    return registry


def build_shopify(settings: Settings, clock: Clock, outbound: OutboundPolicy) -> PlatformProvider:
    """Shopify is offered only when at least one Shopify app is configured (D14)."""
    from app.providers.http.client import SafeHttpClient
    from app.providers.shopify.config import parse_apps
    from app.providers.shopify.provider import ShopifyProvider

    assert settings.SHOPIFY_APPS is not None
    return ShopifyProvider(
        apps=parse_apps(settings.SHOPIFY_APPS.get_secret_value()),
        http_factory=lambda: SafeHttpClient(outbound),
        api_version=settings.SHOPIFY_API_VERSION,
        scopes=tuple(s.strip() for s in settings.SHOPIFY_SCOPES.split(",") if s.strip()),
        clock=clock,
        install_max_age=settings.SHOPIFY_INSTALL_MAX_AGE,
        default_order_history=settings.SHOPIFY_DEFAULT_ORDER_HISTORY,
        download_hosts=frozenset(
            h.strip().lower() for h in settings.SHOPIFY_BULK_DOWNLOAD_HOSTS.split(",") if h.strip()
        ),
    )
