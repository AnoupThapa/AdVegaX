"""Provider registry: code → implementation. Test-only providers never load when deployed."""

from __future__ import annotations

from app.core.errors import NotFound
from app.core.settings import Settings
from app.providers.base.interfaces import PlatformProvider


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


def build_registry(settings: Settings) -> ProviderRegistry:
    registry = ProviderRegistry(settings)
    if not settings.is_deployed:
        from app.providers.fake.provider import FakeProvider

        registry.register(FakeProvider())
    return registry
