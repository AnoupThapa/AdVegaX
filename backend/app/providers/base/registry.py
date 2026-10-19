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
    if settings.WOOCOMMERCE_ENABLED and outbound is not None:
        registry.register(build_woocommerce(settings, outbound))
    if google_ads_configured(settings) and outbound is not None:
        registry.register(build_google_ads(settings, clock or SystemClock(), outbound))
    if meta_ads_configured(settings) and outbound is not None:
        registry.register(build_meta_ads(settings, clock or SystemClock(), outbound))
    if google_analytics_configured(settings) and outbound is not None:
        registry.register(build_google_analytics(settings, clock or SystemClock(), outbound))
    return registry


def google_analytics_configured(settings: Settings) -> bool:
    """GA4 uses the Google Ads OAuth client (Q-5-2) but no developer token."""
    return bool(
        settings.GOOGLE_ANALYTICS_ENABLED
        and settings.GOOGLE_ADS_CLIENT_ID
        and settings.GOOGLE_ADS_CLIENT_SECRET is not None
    )


def build_google_analytics(
    settings: Settings, clock: Clock, outbound: OutboundPolicy
) -> PlatformProvider:
    """Google Analytics 4, read-only (Phase 5): fixed Google hosts through the SSRF-safe
    client."""
    from app.providers.google_analytics.provider import GoogleAnalyticsProvider
    from app.providers.http.client import SafeHttpClient

    assert settings.GOOGLE_ADS_CLIENT_ID is not None
    assert settings.GOOGLE_ADS_CLIENT_SECRET is not None
    return GoogleAnalyticsProvider(
        client_id=settings.GOOGLE_ADS_CLIENT_ID,
        client_secret=settings.GOOGLE_ADS_CLIENT_SECRET.get_secret_value(),
        api_version=settings.GOOGLE_ANALYTICS_API_VERSION,
        http_factory=lambda: SafeHttpClient(outbound),
        clock=clock,
    )


def meta_ads_configured(settings: Settings) -> bool:
    return bool(
        settings.META_ADS_ENABLED
        and settings.META_APP_ID
        and settings.META_APP_SECRET is not None
        and settings.META_LOGIN_CONFIG_ID
    )


def build_meta_ads(settings: Settings, clock: Clock, outbound: OutboundPolicy) -> PlatformProvider:
    """Meta Ads, read-only (Phase 4): fixed Meta hosts through the SSRF-safe client."""
    from app.providers.http.client import SafeHttpClient
    from app.providers.meta_ads.provider import MetaAdsProvider

    assert settings.META_APP_ID is not None
    assert settings.META_APP_SECRET is not None
    assert settings.META_LOGIN_CONFIG_ID is not None
    return MetaAdsProvider(
        app_id=settings.META_APP_ID,
        app_secret=settings.META_APP_SECRET.get_secret_value(),
        login_config_id=settings.META_LOGIN_CONFIG_ID,
        api_version=settings.META_API_VERSION,
        http_factory=lambda: SafeHttpClient(outbound),
        clock=clock,
    )


def google_ads_configured(settings: Settings) -> bool:
    return bool(
        settings.GOOGLE_ADS_ENABLED
        and settings.GOOGLE_ADS_CLIENT_ID
        and settings.GOOGLE_ADS_CLIENT_SECRET is not None
        and settings.GOOGLE_ADS_DEVELOPER_TOKEN is not None
    )


def build_google_ads(
    settings: Settings, clock: Clock, outbound: OutboundPolicy
) -> PlatformProvider:
    """Google Ads, read-only (Phase 3): fixed Google hosts through the SSRF-safe client."""
    from app.providers.google_ads.provider import GoogleAdsProvider
    from app.providers.http.client import SafeHttpClient

    assert settings.GOOGLE_ADS_CLIENT_ID is not None
    assert settings.GOOGLE_ADS_CLIENT_SECRET is not None
    assert settings.GOOGLE_ADS_DEVELOPER_TOKEN is not None
    return GoogleAdsProvider(
        client_id=settings.GOOGLE_ADS_CLIENT_ID,
        client_secret=settings.GOOGLE_ADS_CLIENT_SECRET.get_secret_value(),
        developer_token=settings.GOOGLE_ADS_DEVELOPER_TOKEN.get_secret_value(),
        api_version=settings.GOOGLE_ADS_API_VERSION,
        http_factory=lambda: SafeHttpClient(outbound),
        clock=clock,
        daily_operations=settings.GOOGLE_ADS_DAILY_OPERATIONS,
    )


def build_woocommerce(settings: Settings, outbound: OutboundPolicy) -> PlatformProvider:
    """WooCommerce needs no platform app: merchants approve a key on their own store."""
    from app.providers.http.client import SafeHttpClient
    from app.providers.woocommerce.provider import WooCommerceProvider

    major, minor = (int(p) for p in settings.WOOCOMMERCE_MIN_VERSION.split("."))
    return WooCommerceProvider(
        http_factory=lambda: SafeHttpClient(outbound),
        app_name=settings.WOOCOMMERCE_APP_NAME,
        min_version=(major, minor),
        reconcile_interval=settings.WOOCOMMERCE_RECONCILE_INTERVAL,
    )


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
