"""Shopify provider unit tests: store addresses, signatures, configuration, connect, discovery and
error mapping — against the in-process simulator (no network; PHASE_02A_PLAN §14)."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from app.core.clock import Clock
from app.providers.base.capabilities import Capability
from app.providers.base.errors import (
    AccountMismatchError,
    AuthExpiredError,
    InvalidConnectParamsError,
    InvalidRequestError,
    InvalidSignatureError,
    MissingScopesError,
    PermissionDeniedError,
    RateLimitedError,
    RetryableError,
    UnsupportedOperationError,
)
from app.providers.base.types import AuthorizationRequest, ResourceKind
from app.providers.shopify.config import ShopifyApp, ShopifyConfigError, app_for_shop, parse_apps
from app.providers.shopify.shops import ShopDomainError, is_valid_shop, normalize_shop
from app.providers.shopify.signatures import sign_body, sign_query, verify_body, verify_query

from tests.shopify_sim import (
    CLIENT_ID,
    CLIENT_SECRET,
    ShopifySim,
    build_provider,
    callback_params,
    install_params,
)

SHOP = "eve-zone.myshopify.com"


class FixedClock(Clock):
    def __init__(self, at: float | None = None) -> None:
        self._at = at or time.time()

    def now(self) -> datetime:
        return datetime.fromtimestamp(self._at, UTC)


@pytest.fixture
def sim() -> ShopifySim:
    s = ShopifySim()
    s.add_shop(SHOP)
    return s


@pytest.fixture
def provider(sim):
    return build_provider(sim, FixedClock())


def _authorize(provider, shop: str = SHOP) -> str:
    prepared = provider.prepare_connect({"shop_domain": shop})
    return provider.authorization_url(
        AuthorizationRequest(
            state="st-123",
            redirect_uri="https://api.example.test/api/v1/connections/shopify/callback",
            provider_params=prepared.params,
        )
    )


# ------------------------------------------------------------------ store addresses
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("eve-zone", SHOP),
        ("Eve-Zone", SHOP),
        (" eve-zone.myshopify.com ", SHOP),
        ("https://eve-zone.myshopify.com/admin", SHOP),
        ("http://eve-zone.myshopify.com", SHOP),
    ],
)
def test_store_address_normalization(raw, expected):
    assert normalize_shop(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "-bad.myshopify.com",
        "eve-zone.myshopify.com.attacker.example",
        "eve-zone.example.com",
        "evil@eve-zone.myshopify.com",
        "eve-zone.myshopify.com:8443",
        "127.0.0.1",
        "eve zone",
        "eve_zone",
        "a" * 300,
        "eve-zone.myshopify.com?x=1",
    ],
)
def test_store_address_rejections(raw):
    with pytest.raises(ShopDomainError):
        normalize_shop(raw)
    assert not is_valid_shop(raw)


# ------------------------------------------------------------------ signatures
def test_query_signature_matches_shopify_algorithm():
    # Remove hmac, sort keys, join key=value with '&', hex HMAC-SHA256 with the client secret.
    params = {"shop": SHOP, "timestamp": "1700000000", "code": "abc", "state": "s"}
    signed = {**params, "hmac": sign_query(params, CLIENT_SECRET)}
    assert verify_query(signed, CLIENT_SECRET)
    assert not verify_query(signed, "another-secret-value-123")
    assert not verify_query({**signed, "shop": "other.myshopify.com"}, CLIENT_SECRET)
    assert not verify_query({**params, "hmac": ""}, CLIENT_SECRET)
    assert not verify_query({**params, "hmac": "00"}, CLIENT_SECRET)
    # The legacy 'signature' parameter is excluded from the message, like 'hmac'.
    assert verify_query({**signed, "signature": "ignored"}, CLIENT_SECRET)


def test_body_signature_for_webhooks():
    body = b'{"id": 1}'
    header = sign_body(body, CLIENT_SECRET)
    assert verify_body(body, header, CLIENT_SECRET)
    assert not verify_body(body + b" ", header, CLIENT_SECRET)
    assert not verify_body(body, None, CLIENT_SECRET)
    assert not verify_body(body, "not base64 !!", CLIENT_SECRET)


# ------------------------------------------------------------------ configuration
def test_apps_configuration_parsing_and_selection():
    apps = parse_apps(
        '[{"client_id": "eve", "client_secret": "s1-0123456789abcdef", "shops": ["eve-zone"]},'
        ' {"client_id": "dev", "client_secret": "s2-0123456789abcdef"}]'
    )
    assert apps[0].shops == frozenset({SHOP})
    assert app_for_shop(apps, SHOP).client_id == "eve"  # explicit store beats wildcard
    assert app_for_shop(apps, "other.myshopify.com").client_id == "dev"
    assert "s1-" not in repr(apps[0])  # the secret never appears in logs/reprs
    only_eve = (ShopifyApp("eve", "s1-0123456789abcdef", frozenset({SHOP})),)
    assert app_for_shop(only_eve, "other.myshopify.com") is None


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "{}",
        '[{"client_secret": "0123456789abcdefg"}]',
        '[{"client_id": "a", "client_secret": "short"}]',
        '[{"client_id": "a", "client_secret": "0123456789abcdefg", "shops": ["bad.example"]}]',
        '[{"client_id": "a", "client_secret": "0123456789abcdefg"},'
        ' {"client_id": "a", "client_secret": "0123456789abcdefg"}]',
    ],
)
def test_bad_apps_configuration_is_refused_without_echoing_secrets(raw):
    with pytest.raises(ShopifyConfigError) as error:
        parse_apps(raw)
    assert "0123456789abcdefg" not in str(error.value)


# ------------------------------------------------------------------ connect
def test_prepare_connect_validates_and_names_the_account(provider):
    prepared = provider.prepare_connect({"shop_domain": "Eve-Zone"})
    assert prepared.params == {"shop_domain": SHOP}
    assert prepared.account_id == SHOP
    for bad in ({}, {"shop_domain": "evil.example"}, {"shop_domain": SHOP, "extra": "x"}):
        with pytest.raises(InvalidConnectParamsError):
            provider.prepare_connect(bad)


def test_prepare_connect_refuses_a_store_no_configured_app_serves(sim):
    only_eve = (ShopifyApp(CLIENT_ID, CLIENT_SECRET, frozenset({SHOP})),)
    provider = build_provider(sim, FixedClock(), apps=only_eve)
    with pytest.raises(InvalidConnectParamsError):
        provider.prepare_connect({"shop_domain": "someone-else"})


def test_authorization_url_targets_the_store_with_read_only_scopes(provider):
    url = _authorize(provider)
    assert url.startswith(f"https://{SHOP}/admin/oauth/authorize?")
    assert f"client_id={CLIENT_ID}" in url
    assert "scope=read_products%2Cread_inventory%2Cread_orders" in url
    assert "state=st-123" in url
    assert "write_" not in url
    assert CLIENT_SECRET not in url


def test_complete_authorization_exchanges_for_expiring_tokens(provider, sim):
    url = _authorize(provider)
    result = provider.complete_authorization(
        callback_params(url),
        redirect_uri="unused",
        code_verifier=None,
        provider_params={"shop_domain": SHOP},
    )
    (call,) = sim.token_calls
    form = call.content.decode()
    assert "expiring=1" in form and "client_secret=" in form
    assert CLIENT_SECRET not in str(call.url)  # the secret travels in the body, never the URL
    assert call.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert result.external_account_id == SHOP
    assert result.token_expires_in_seconds == 3600
    assert result.refresh_expires_in_seconds == 7_776_000
    assert result.secrets["shop"] == SHOP and result.secrets["refresh_token"]
    assert "shpat_" not in repr(result)  # secrets are hidden from reprs
    assert set(result.granted_scopes) == {"read_products", "read_inventory", "read_orders"}


def test_callback_with_bad_signature_is_refused_before_any_exchange(provider, sim):
    url = _authorize(provider)
    with pytest.raises(InvalidSignatureError):
        provider.complete_authorization(
            callback_params(url, secret="wrong-secret-0123456789"),
            redirect_uri="x",
            code_verifier=None,
            provider_params={"shop_domain": SHOP},
        )
    assert sim.token_calls == []


def test_callback_for_another_store_is_refused(provider, sim):
    sim.add_shop("other.myshopify.com")
    url = _authorize(provider)
    with pytest.raises(AccountMismatchError):
        provider.complete_authorization(
            callback_params(url, shop="other.myshopify.com"),
            redirect_uri="x",
            code_verifier=None,
            provider_params={"shop_domain": SHOP},
        )
    assert sim.token_calls == []


def test_fewer_permissions_than_needed_are_refused(provider, sim):
    sim.granted_scope = "read_products"
    url = _authorize(provider)
    with pytest.raises(MissingScopesError):
        provider.complete_authorization(
            callback_params(url),
            redirect_uri="x",
            code_verifier=None,
            provider_params={"shop_domain": SHOP},
        )


def test_write_scope_satisfies_the_matching_read_scope(provider, sim):
    sim.granted_scope = "write_products,read_inventory,read_orders"
    url = _authorize(provider)
    result = provider.complete_authorization(
        callback_params(url),
        redirect_uri="x",
        code_verifier=None,
        provider_params={"shop_domain": SHOP},
    )
    assert "write_products" in result.granted_scopes


@pytest.mark.parametrize(("status", "error"), [(400, InvalidRequestError), (503, RetryableError)])
def test_token_endpoint_failures_are_normalized(provider, sim, status, error):
    sim.token_status = status
    url = _authorize(provider)
    with pytest.raises(error) as raised:
        provider.complete_authorization(
            callback_params(url),
            redirect_uri="x",
            code_verifier=None,
            provider_params={"shop_domain": SHOP},
        )
    assert 'invalid_request"' not in str(raised.value)  # no response body in errors


# ------------------------------------------------------------------ install
def test_shopify_initiated_install_is_verified_and_fresh(sim):
    now = time.time()
    provider = build_provider(sim, FixedClock(now))
    assert provider.capabilities.supports(Capability.APP_INSTALL)
    assert provider.verify_install(install_params(SHOP, int(now))) == SHOP
    with pytest.raises(InvalidSignatureError):
        provider.verify_install(install_params(SHOP, int(now), secret="wrong-secret-0123456789"))
    with pytest.raises(InvalidSignatureError):  # stale: possible replay
        provider.verify_install(install_params(SHOP, int(now) - 3600))
    with pytest.raises(InvalidSignatureError):
        provider.verify_install({**install_params(SHOP, int(now)), "timestamp": "soon"})
    with pytest.raises(InvalidConnectParamsError):
        provider.verify_install(install_params("evil.example", int(now)))


# ------------------------------------------------------------------ discovery & errors
def _secrets(token: str = "shpat_sim_access_1") -> dict[str, str]:  # noqa: S107
    return {"shop": SHOP, "access_token": token, "refresh_token": "shprt_x"}


def test_discovery_returns_exactly_one_store(provider):
    (store,) = provider.discover_resources(_secrets())
    assert store.kind is ResourceKind.STORE
    assert store.external_id == "gid://shopify/Shop/1001"
    assert (store.display_name, store.currency, store.timezone) == (
        "Eve Zone Test",
        "AUD",
        "Australia/Sydney",
    )


def test_discovery_refuses_a_token_answering_for_another_store(provider, sim):
    sim.shops[SHOP].domain = "different.myshopify.com"
    with pytest.raises(AccountMismatchError):
        provider.discover_resources(_secrets())


@pytest.mark.parametrize(
    ("status", "errors", "expected"),
    [
        (401, None, AuthExpiredError),
        (403, None, PermissionDeniedError),
        (402, None, PermissionDeniedError),
        (429, None, RateLimitedError),
        (500, None, RetryableError),
        (200, [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}], RateLimitedError),
        (
            200,
            [{"message": "denied", "extensions": {"code": "ACCESS_DENIED"}}],
            PermissionDeniedError,
        ),
        (200, [{"message": "secret shpat_xyz"}], InvalidRequestError),
    ],
)
def test_graphql_errors_are_normalized_without_echoing_bodies(
    provider, sim, status, errors, expected
):
    sim.graphql_status, sim.graphql_errors = status, errors
    with pytest.raises(expected) as raised:
        provider.discover_resources(_secrets())
    assert "shpat_" not in str(raised.value)
    if expected is RateLimitedError and status == 429:
        assert raised.value.retry_after_seconds == 2.0


def test_invalid_token_is_auth_expired(provider):
    with pytest.raises(AuthExpiredError):
        provider.discover_resources(_secrets(token="revoked"))


def test_sync_and_revoke_are_not_available_yet(provider):
    with pytest.raises(UnsupportedOperationError):
        provider.revoke(_secrets())
    (store,) = provider.discover_resources(_secrets())
    with pytest.raises(UnsupportedOperationError):
        provider.sync_resource(_secrets(), store)
