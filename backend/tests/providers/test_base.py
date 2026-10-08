"""Provider framework: availability invariants, capabilities, types, registry, PKCE."""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.core.settings import Settings
from app.providers.base.availability import Availability, MetricValue
from app.providers.base.capabilities import Capability, ProviderCapabilities
from app.providers.base.pkce import pkce_challenge
from app.providers.base.registry import ProviderRegistry, UnknownProvider, build_registry
from app.providers.base.types import Money
from app.providers.fake.provider import FakeProvider

from tests.unit.test_settings import SECURE


def test_metric_value_never_zero_for_missing_data():
    ok = MetricValue.available(Decimal("12.50"), source="fake", currency="AUD")
    assert ok.availability is Availability.AVAILABLE
    for state in (
        Availability.UNAVAILABLE,
        Availability.UNSUPPORTED,
        Availability.NOT_SYNCHRONIZED,
    ):
        missing = MetricValue.missing(state, source="fake")
        assert missing.value is None
    with pytest.raises(ValueError, match="must not carry a value"):
        MetricValue(Decimal(0), Availability.UNSUPPORTED, "fake")
    with pytest.raises(ValueError, match="must carry a value"):
        MetricValue(None, Availability.AVAILABLE, "fake")


def test_capabilities_drive_availability():
    caps = ProviderCapabilities(frozenset({Capability.WEBHOOKS}))
    assert caps.supports(Capability.WEBHOOKS)
    assert caps.availability_of(Capability.PRODUCT_COST) is Availability.UNSUPPORTED
    assert caps.availability_of(Capability.WEBHOOKS) is Availability.NOT_SYNCHRONIZED
    assert caps.as_dict()["webhooks"] is True
    assert caps.to_json() == {"supported": ["webhooks"]}


def test_money_requires_decimal_and_iso_currency():
    assert Money(Decimal("1.00"), "AUD").currency == "AUD"
    with pytest.raises(TypeError):
        Money(1.0, "AUD")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Money(Decimal(1), "aud")


def test_registry_rules():
    registry = build_registry(Settings())
    assert registry.codes() == ["fake"]
    assert registry.get("fake").code == "fake"
    with pytest.raises(UnknownProvider):
        registry.get("shopify")
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeProvider())
    assert [p.code for p in registry.all()] == ["fake"]
    deployed = Settings(**SECURE)
    assert build_registry(deployed).codes() == []
    assert build_registry(deployed).all() == []
    with pytest.raises(RuntimeError, match="test-only"):
        ProviderRegistry(deployed).register(FakeProvider())


def test_pkce_rfc7636_vector():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
