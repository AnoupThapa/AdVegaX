"""WooCommerce provider details not reached through the connect journey (task 2B-04)."""

from __future__ import annotations

import pytest
from app.providers.base.errors import (
    AuthExpiredError,
    InvalidConnectParamsError,
    InvalidRequestError,
    UnsupportedOperationError,
)
from app.providers.base.types import (
    AuthorizationRequest,
    ChangedObject,
    ResourceDescriptor,
    ResourceKind,
)
from app.providers.woocommerce.client import UnexpectedResponseError
from app.providers.woocommerce.provider import WooCommerceTooOldError

from tests.woocommerce_sim import WooSim, build_provider

HOST = "shop.example.com"
STORE = {"store_url": f"https://{HOST}"}


@pytest.fixture
def sim():
    s = WooSim()
    s.add_store(HOST)
    return s


@pytest.mark.parametrize(
    "params",
    [{}, {"store_url": "https://a.example", "extra": "x"}, {"shop_domain": "x"}],
)
def test_only_the_store_address_is_accepted(sim, params):
    with pytest.raises(InvalidConnectParamsError):
        build_provider(sim).prepare_connect(params)


def test_the_authorize_page_needs_a_delivery_address(sim):
    with pytest.raises(InvalidConnectParamsError):
        build_provider(sim).authorization_url(
            AuthorizationRequest(state="s", redirect_uri="https://api/cb", provider_params=STORE)
        )


@pytest.mark.parametrize(
    "fields",
    [
        {
            "consumer_key": "ck_short",
            "consumer_secret": "cs_" + "a" * 40,
            "key_permissions": "read",
        },
        {"consumer_key": "ck_" + "a" * 40, "consumer_secret": "nope", "key_permissions": "read"},
        {"consumer_key": "ck_" + "a" * 40 + "!", "consumer_secret": "cs_" + "a" * 40},
    ],
)
def test_malformed_keys_are_refused_without_calling_the_store(sim, fields):
    with pytest.raises(InvalidRequestError):
        build_provider(sim).complete_authorization(
            fields, redirect_uri="x", code_verifier=None, provider_params=STORE
        )
    assert sim.requests == []


@pytest.mark.parametrize("version", ["8.9.9", "abc", "", "9"])
def test_old_or_unreadable_versions_are_refused(sim, version):
    sim.stores[HOST].version = version
    ck, cs = sim.issue_key(HOST)
    with pytest.raises(WooCommerceTooOldError):
        build_provider(sim).complete_authorization(
            {"consumer_key": ck, "consumer_secret": cs, "key_permissions": "read"},
            redirect_uri="x",
            code_verifier=None,
            provider_params=STORE,
        )


def test_minimum_version_is_configurable(sim):
    sim.stores[HOST].version = "9.4.0"
    ck, cs = sim.issue_key(HOST)
    fields = {"consumer_key": ck, "consumer_secret": cs, "key_permissions": "read", "key_id": "7"}
    result = build_provider(sim).complete_authorization(
        fields, redirect_uri="x", code_verifier=None, provider_params=STORE
    )
    assert result.secrets["key_id"] == "7" and result.granted_scopes == ("read",)
    with pytest.raises(WooCommerceTooOldError):
        build_provider(sim, min_version=(10, 0)).complete_authorization(
            fields, redirect_uri="x", code_verifier=None, provider_params=STORE
        )


def test_discovery_leaves_unknown_currency_and_zone_empty(sim):
    store = sim.stores[HOST]
    store.currency, store.timezone_string, store.gmt_offset, store.name = "aud", "", "5.5", ""
    ck, cs = sim.issue_key(HOST)
    (found,) = build_provider(sim).discover_resources(
        {"store_url": f"https://{HOST}", "consumer_key": ck, "consumer_secret": cs}
    )
    assert (found.currency, found.timezone, found.display_name) == (None, None, HOST)


def test_discovery_needs_complete_credentials(sim):
    with pytest.raises(AuthExpiredError):
        build_provider(sim).discover_resources({"store_url": f"https://{HOST}"})


def test_unexpected_status_shapes_are_refused(sim):
    sim.stores[HOST].data["/system_status"] = ["not", "an", "object"]
    ck, cs = sim.issue_key(HOST)
    provider = build_provider(sim)
    original = sim.handler

    def odd(request):
        if request.url.path.endswith("/system_status"):
            import httpx

            return httpx.Response(200, json=["not", "an", "object"])
        return original(request)

    sim.handler = odd  # type: ignore[method-assign]
    with pytest.raises(UnexpectedResponseError):
        provider.discover_resources(
            {"store_url": f"https://{HOST}", "consumer_key": ck, "consumer_secret": cs}
        )


def test_operations_woocommerce_does_not_have(sim):
    provider = build_provider(sim)
    resource = ResourceDescriptor(ResourceKind.STORE, HOST)
    for call in (
        lambda: provider.verify_install({}),
        lambda: provider.sync_resource({}, resource),
        lambda: provider.revoke({}),
        lambda: provider.refresh_credentials({}),
        lambda: provider.parse_webhook({}, b""),
        lambda: provider.fetch_product({}, "1"),
        lambda: provider.fetch_order({}, "1"),
    ):
        with pytest.raises(UnsupportedOperationError):
            call()
    assert provider.history_limit(("read",)) is None
    assert provider.webhook_target("order.updated").object is ChangedObject.NONE
