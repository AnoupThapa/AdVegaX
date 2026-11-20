"""Shopify connect through the real API, database and job runner (task 2A-03).

Start with a store address → Shopify (simulated) → signed callback → connection + discovered
store; the one-live-connection-per-store rule (Q6) is enforced *before* any token exchange;
reconnecting reuses the connection; Shopify-initiated installs are verified and store nothing.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from tests.shopify_sim import (
    ShopifySim,
    build_provider,
    callback_params,
    install_params,
)

SHOP = "eve-zone.myshopify.com"


@pytest.fixture
def sim(runtime, clock):
    s = ShopifySim()
    s.add_shop(SHOP)
    runtime.providers.register(build_provider(s, clock))
    return s


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup("shopify-owner@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    return c


def _start(client, org, shop="eve-zone"):
    return client.post(
        f"/organizations/{org}/connections/shopify/start", {"params": {"shop_domain": shop}}
    )


def _callback(client, params):
    response = client.http.get(
        "/api/v1/connections/shopify/callback", params=params, follow_redirects=False
    )
    assert response.status_code == 303
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


def _connect(client, org, shop="eve-zone"):
    started = _start(client, org, shop)
    assert started.status_code == 200, started.text
    return _callback(client, callback_params(started.json()["data"]["authorize_url"]))


def test_provider_is_listed_for_signed_in_users(owner):
    providers = {p["code"]: p for p in owner.get("/providers").json()["data"]}
    shopify = providers["shopify"]
    assert shopify["display_name"] == "Shopify"
    assert shopify["category"] == "commerce"
    assert shopify["test_only"] is False
    assert shopify["capabilities"]["app_install"] is True
    assert shopify["capabilities"]["token_revocation"] is False


def test_connect_creates_connection_and_discovers_the_store(owner, sim, admin_engine):
    result = _connect(owner, owner.org)
    assert result["status"] == "connected", result
    conn = result["connection_id"]
    detail = owner.get(f"/organizations/{owner.org}/connections/{conn}").json()["data"]
    assert detail["provider"] == "shopify"
    assert detail["account_label"] == SHOP
    assert "access_token" not in json.dumps(detail)
    (store,) = owner.get(f"/organizations/{owner.org}/connections/{conn}/resources").json()["data"]
    assert (store["kind"], store["display_name"], store["currency"]) == (
        "store",
        "Eve Zone Test",
        "AUD",
    )
    assert store["linked"] is False  # discovery never links (A6)
    with admin_engine.begin() as db:
        row = db.execute(
            text(
                "SELECT c.external_account_id, k.token_expires_at IS NOT NULL, "
                "k.refresh_expires_at IS NOT NULL, k.ciphertext IS NOT NULL "
                "FROM external_connections c JOIN external_connection_credentials k "
                "ON k.connection_id = c.id WHERE c.id = :id"
            ),
            {"id": conn},
        ).one()
    assert row == (SHOP, True, True, True)
    assert len(sim.token_calls) == 1


@pytest.mark.parametrize(
    "shop", ["", "evil.example", "eve-zone.myshopify.com.attacker.example", "a b"]
)
def test_invalid_store_address_is_refused(owner, shop, sim):
    response = _start(owner, owner.org, shop)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CONNECT_PARAMS"
    assert sim.requests == []


def test_unknown_parameters_are_refused(owner):
    response = owner.post(
        f"/organizations/{owner.org}/connections/shopify/start",
        {"params": {"shop_domain": "eve-zone", "redirect_uri": "https://evil.example"}},
    )
    assert response.status_code == 422


def test_viewers_cannot_start_a_connection(owner, make_client):
    viewer = make_client()
    viewer.signup("viewer@example.com")
    owner.invite_and_join(owner.org, viewer, "viewer@example.com", "viewer")
    assert _start(viewer, owner.org).status_code == 403


def test_tampered_callback_connects_nothing(owner, sim):
    started = _start(owner, owner.org).json()["data"]["authorize_url"]
    params = callback_params(started)
    params["code"] = "swapped-code"  # signature no longer matches
    result = _callback(owner, params)
    assert (result["status"], result["code"]) == ("error", "invalid_signature")
    assert sim.token_calls == []
    assert owner.get(f"/organizations/{owner.org}/connections").json()["data"] == []


def test_callback_for_a_different_store_connects_nothing(owner, sim):
    sim.add_shop("other.myshopify.com")
    started = _start(owner, owner.org).json()["data"]["authorize_url"]
    result = _callback(owner, callback_params(started, shop="other.myshopify.com"))
    assert result["code"] == "account_mismatch"
    assert sim.token_calls == []


def test_second_organization_is_refused_at_start(owner, make_client, sim):
    assert _connect(owner, owner.org)["status"] == "connected"
    other = make_client()
    other.signup("agency@example.com")
    other_org = other.create_org("Agency")["id"]
    response = _start(other, other_org)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACCOUNT_IN_USE"
    assert len(sim.token_calls) == 1  # only the first organization's exchange


def test_second_organization_is_refused_before_the_token_exchange(owner, make_client, sim):
    """Both start while the store is free; the first finishes; the second must not exchange
    its code — that would retire the first organization's token at Shopify (§6.4)."""
    other = make_client()
    other.signup("agency2@example.com")
    other_org = other.create_org("Agency Two")["id"]
    url_a = _start(owner, owner.org).json()["data"]["authorize_url"]
    url_b = _start(other, other_org).json()["data"]["authorize_url"]
    assert _callback(owner, callback_params(url_a))["status"] == "connected"
    result = _callback(other, callback_params(url_b))
    assert (result["status"], result["code"]) == ("error", "account_in_use")
    assert len(sim.token_calls) == 1
    assert other.get(f"/organizations/{other_org}/connections").json()["data"] == []


def test_reconnect_reuses_the_connection_and_store(owner, sim):
    first = _connect(owner, owner.org)["connection_id"]
    (resource,) = owner.get(f"/organizations/{owner.org}/connections/{first}/resources").json()[
        "data"
    ]
    owner.post(f"/organizations/{owner.org}/resources/{resource['id']}/link")
    second = _connect(owner, owner.org)
    assert second["connection_id"] == first  # no duplicate connection or store
    connections = owner.get(f"/organizations/{owner.org}/connections").json()["data"]
    assert len(connections) == 1 and connections[0]["status"] == "active"
    resources = owner.get(f"/organizations/{owner.org}/connections/{first}/resources").json()[
        "data"
    ]
    assert [r["id"] for r in resources] == [resource["id"]]
    assert resources[0]["linked"] is True  # the link survived the reconnect
    assert len(sim.token_calls) == 2


def test_reconnect_after_disconnect_reuses_the_connection(owner, sim):
    first = _connect(owner, owner.org)["connection_id"]
    disconnected = owner.post(f"/organizations/{owner.org}/connections/{first}/disconnect")
    assert disconnected.json()["data"]["status"] == "revoked"
    again = _connect(owner, owner.org)
    assert again["connection_id"] == first
    detail = owner.get(f"/organizations/{owner.org}/connections/{first}").json()["data"]
    assert detail["status"] == "active" and detail["revoked_at"] is None


def test_disconnected_store_can_move_to_another_organization(owner, make_client, sim):
    first = _connect(owner, owner.org)["connection_id"]
    owner.post(f"/organizations/{owner.org}/connections/{first}/disconnect")
    other = make_client()
    other.signup("newowner@example.com")
    other_org = other.create_org("New Owner")["id"]
    assert _connect(other, other_org)["status"] == "connected"


def test_reconnect_and_connect_are_audited(owner, admin_engine):
    _connect(owner, owner.org)
    _connect(owner, owner.org)
    with admin_engine.begin() as db:
        actions = [
            r[0]
            for r in db.execute(
                text(
                    "SELECT action FROM audit_logs WHERE organization_id = :o "
                    "AND action LIKE 'connection.%' ORDER BY created_at"
                ),
                {"o": owner.org},
            )
        ]
        logged = " ".join(
            str(r[0]) for r in db.execute(text("SELECT row_to_json(a) FROM audit_logs a"))
        )
    assert actions.count("connection.created") == 1
    assert actions.count("connection.reconnected") == 1
    assert "shpat_" not in logged and "shprt_" not in logged  # tokens never audited


def test_shopify_initiated_install_sends_the_browser_to_choose_an_organization(client, clock, sim):
    params = install_params(SHOP, int(clock.now().timestamp()))
    response = client.http.get(
        "/api/v1/connections/shopify/install", params=params, follow_redirects=False
    )
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.path == "/connect/shopify"
    assert parse_qs(location.query) == {"account": [SHOP]}
    assert sim.requests == []  # nothing is exchanged or stored before sign-in


@pytest.mark.parametrize(
    "tamper",
    [
        lambda p: {**p, "hmac": "0" * 64},
        lambda p: {**p, "shop": "other.myshopify.com"},
        lambda p: {k: v for k, v in p.items() if k != "hmac"},
    ],
)
def test_forged_install_is_refused(client, clock, sim, tamper):
    params = tamper(install_params(SHOP, int(clock.now().timestamp())))
    response = client.http.get(
        "/api/v1/connections/shopify/install", params=params, follow_redirects=False
    )
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["status"] == ["error"]
    assert query["code"][0] in ("invalid_signature", "invalid_connect_params")


def test_install_for_platforms_without_it_or_unknown_platforms(client):
    for provider, code in (("fake", "unsupported"), ("nope", "unknown_provider")):
        response = client.http.get(
            f"/api/v1/connections/{provider}/install", follow_redirects=False
        )
        assert parse_qs(urlsplit(response.headers["location"]).query)["code"] == [code]


def test_fake_platform_still_rejects_connect_parameters(owner):
    response = owner.post(
        f"/organizations/{owner.org}/connections/fake/start", {"params": {"x": "1"}}
    )
    assert response.status_code == 422
    assert owner.post(f"/organizations/{owner.org}/connections/fake/start").status_code == 200


def test_tokens_and_secrets_never_reach_logs(owner, sim, caplog):
    import logging

    from tests.shopify_sim import CLIENT_SECRET

    caplog.set_level(logging.DEBUG)
    _connect(owner, owner.org)
    sim.token_status = 400
    _connect(owner, owner.org)  # a failing exchange is logged as a code only
    assert "shpat_" not in caplog.text and "shprt_" not in caplog.text
    assert CLIENT_SECRET not in caplog.text
    assert "connect_failed" in caplog.text


def test_race_with_another_organization_is_caught_by_the_database(
    owner, make_client, sim, monkeypatch
):
    """If two organizations pass the pre-check at the same moment, the unique index still
    allows only one live connection; the loser is told the store is in use."""
    from app.domains.integrations.service import IntegrationService

    assert _connect(owner, owner.org)["status"] == "connected"
    other = make_client()
    other.signup("racer@example.com")
    other_org = other.create_org("Racer")["id"]
    monkeypatch.setattr(IntegrationService, "_live_account_owner", lambda *a, **k: None)
    result = _connect(other, other_org)
    assert (result["status"], result["code"]) == ("error", "account_in_use")
    assert other.get(f"/organizations/{other_org}/connections").json()["data"] == []


def test_registry_offers_shopify_only_when_an_app_is_configured(settings, clock):
    from app.providers.base.registry import build_registry
    from app.runtime import outbound_policy

    assert (
        "shopify"
        not in build_registry(settings, clock=clock, outbound=outbound_policy(settings)).codes()
    )
    configured = settings.model_copy(
        update={
            "SHOPIFY_APPS": SecretStr('[{"client_id": "x", "client_secret": "0123456789abcdefgh"}]')
        }
    )
    registry = build_registry(configured, clock=clock, outbound=outbound_policy(configured))
    assert "shopify" in registry.codes()
    with pytest.raises(ValueError, match="SHOPIFY_APPS"):
        build_registry(
            settings.model_copy(update={"SHOPIFY_APPS": SecretStr("nope")}),
            clock=clock,
            outbound=outbound_policy(settings),
        )
