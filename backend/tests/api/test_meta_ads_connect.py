"""Meta connect through the real API, database and job runner (task 4-02, PLAN §6).

Start → Meta's login dialog (simulated Facebook Login for Business: configuration id, PKCE) →
callback → the code is exchanged on the server, then for the long-lived token → ``debug_token``
confirms the app, the permissions and the person → the encrypted token with its expiry date.
A token Meta no longer accepts means "Needs reconnecting"; reconnecting with the same Facebook
account reuses the connection; disconnect removes AdVegaX's permission at Meta. No token or
the app secret ever appears in a response, the audit log or the logs.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from app.providers.base.registry import build_registry
from pydantic import SecretStr
from sqlalchemy import text

from tests.meta_sim import (
    API_VERSION,
    APP_ID,
    APP_SECRET,
    CONFIG_ID,
    LONG_LIVED_SECONDS,
    MetaSim,
    build_provider,
)

USER = "10160000000000001"


@pytest.fixture
def sim(runtime, clock):
    s = MetaSim(clock=clock)
    s.add_user(USER)
    runtime.providers.register(build_provider(s))
    return s


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup("meta-owner@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    return c


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def _start(client, params=None):
    return client.post(
        f"/organizations/{client.org}/connections/meta_ads/start", {"params": params or {}}
    )


def _callback(client, params):
    response = client.http.get(
        "/api/v1/connections/meta_ads/callback", params=params, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


def _connect(client, sim, user=USER, **approve):
    started = _start(client)
    assert started.status_code == 200, started.text
    return _callback(client, sim.approve(started.json()["data"]["authorize_url"], user, **approve))


# ------------------------------------------------------------------ offered and started
def test_meta_is_offered_only_when_fully_configured(settings):
    def codes(**changes):
        return build_registry(settings.model_copy(update=changes), outbound=object()).codes()

    assert "meta_ads" not in codes()
    assert "meta_ads" not in codes(META_ADS_ENABLED=True)  # no app or configuration
    complete = {
        "META_ADS_ENABLED": True,
        "META_APP_ID": "1234567890",
        "META_APP_SECRET": SecretStr("s"),
        "META_LOGIN_CONFIG_ID": "555555555",
    }
    assert "meta_ads" in codes(**complete)
    assert "meta_ads" not in codes(**{**complete, "META_LOGIN_CONFIG_ID": None})
    assert "meta_ads" not in codes(**{**complete, "META_ADS_ENABLED": False})


def test_meta_is_listed_as_advertising_without_write_capabilities(owner):
    meta = {p["code"]: p for p in owner.get("/providers").json()["data"]}["meta_ads"]
    assert (meta["display_name"], meta["category"], meta["test_only"]) == (
        "Meta",
        "advertising",
        False,
    )
    caps = meta["capabilities"]
    assert caps["pkce"] and caps["token_revocation"]
    assert not caps["token_refresh"]  # long-lived tokens are renewed only by signing in again
    assert not caps["create_campaign"] and not caps["validate_only"]


def test_start_opens_metas_login_with_the_configuration_and_pkce(owner):
    started = _start(owner)
    assert started.status_code == 200
    url = urlsplit(started.json()["data"]["authorize_url"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert (url.scheme, url.hostname, url.path) == (
        "https",
        "www.facebook.com",
        f"/{API_VERSION}/dialog/oauth",
    )
    assert (query["client_id"], query["config_id"], query["response_type"]) == (
        APP_ID,
        CONFIG_ID,
        "code",
    )
    assert "scope" not in query  # the configuration asks for ads_read and business_management
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) == 43
    assert query["redirect_uri"].endswith("/api/v1/connections/meta_ads/callback")
    assert APP_SECRET not in started.text


def test_nothing_is_typed_for_meta(owner):
    response = _start(owner, {"shop_domain": "x"})
    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "INVALID_CONNECT_PARAMS",
    )


def test_viewers_cannot_start(owner, make_client):
    viewer = make_client()
    viewer.signup("meta-viewer@example.com")
    owner.invite_and_join(owner.org, viewer, "meta-viewer@example.com", "viewer")
    viewer.org = owner.org
    assert _start(viewer).status_code == 403


# ------------------------------------------------------------------ the callback
def test_connect_stores_the_long_lived_token_encrypted_and_never_shows_it(
    owner, sim, admin_engine, caplog, clock
):
    caplog.set_level(logging.DEBUG)
    result = _connect(owner, sim)
    assert result["status"] == "connected", result
    conn = result["connection_id"]
    detail = owner.get(f"/organizations/{owner.org}/connections/{conn}")
    data = detail.json()["data"]
    assert (data["provider"], data["account_label"], data["status"]) == (
        "meta_ads",
        "Meta",
        "active",
    )
    assert sorted(data["granted_scopes"]) == ["ads_read", "business_management"]
    code_exchange, long_exchange = sim.calls("/oauth/access_token")
    first = parse_qs(code_exchange.content.decode())
    assert len(first["code_verifier"][0]) >= 43 and "grant_type" not in first
    assert parse_qs(long_exchange.content.decode())["grant_type"] == ["fb_exchange_token"]
    for call in (code_exchange, long_exchange):
        assert call.method == "POST" and not call.url.query  # the secret is never in the address
    (row,) = _rows(
        admin_engine,
        "SELECT c.external_account_id, k.ciphertext, k.token_expires_at "
        "FROM external_connections c JOIN external_connection_credentials k "
        "ON k.connection_id = c.id",
    )
    assert row["external_account_id"] == f"{owner.org}:{USER}"
    expected = clock.now() + timedelta(seconds=LONG_LIVED_SECONDS)
    assert abs((row["token_expires_at"] - expected).total_seconds()) < 5  # about 60 days
    (long_token,) = [t for t, v in sim.tokens.items() if v[2]]
    audit = json.dumps(_rows(admin_engine, "SELECT * FROM audit_logs"), default=str)
    logs = [r.getMessage() for r in caplog.records if "http://testserver" not in r.getMessage()]
    for secret in (*sim.tokens, APP_SECRET):
        assert secret not in detail.text and secret not in audit
        assert secret.encode() not in bytes(row["ciphertext"])
        assert [line for line in logs if secret in line] == []
    assert long_token in {t for t, v in sim.tokens.items() if v[2]}


def test_declining_on_metas_page_connects_nothing(owner, sim, admin_engine):
    assert _connect(owner, sim, declined=True)["status"] == "cancelled"
    assert sim.calls("/oauth/access_token") == []
    assert _rows(admin_engine, "SELECT id FROM external_connections") == []


def test_a_sign_in_without_ads_read_is_explained(owner, sim, admin_engine):
    sim.users[USER].granted = ["business_management"]  # the person unticked ads access
    sim.users[USER].declined = ["ads_read"]
    result = _connect(owner, sim)
    assert (result["status"], result["code"]) == ("error", "missing_scopes")
    assert _rows(admin_engine, "SELECT id FROM external_connections") == []


def test_a_code_meta_refuses_connects_nothing(owner, sim):
    started = _start(owner)
    params = sim.approve(started.json()["data"]["authorize_url"], USER)
    sim._codes.clear()  # e.g. used twice or expired
    result = _callback(owner, params)
    assert (result["status"], result["code"]) == ("error", "meta_sign_in_rejected")


def test_the_state_works_once_and_only_for_the_same_person(owner, sim, make_client):
    started = _start(owner)
    params = sim.approve(started.json()["data"]["authorize_url"], USER)
    other = make_client()
    other.signup("meta-someone-else@example.com")
    assert _callback(other, params)["code"] == "session_mismatch"
    assert _callback(owner, params)["code"] == "invalid_state"  # already consumed


# ------------------------------------------------------------------ reconnect and sharing
def test_reconnecting_with_the_same_facebook_account_reuses_the_connection(owner, sim):
    first = _connect(owner, sim)["connection_id"]
    again = _connect(owner, sim)
    assert again["connection_id"] == first
    assert len(owner.get(f"/organizations/{owner.org}/connections").json()["data"]) == 1


def test_another_facebook_account_is_a_second_connection(owner, sim):
    sim.add_user("10160000000000009")
    first = _connect(owner, sim)["connection_id"]
    second = _connect(owner, sim, user="10160000000000009")["connection_id"]
    assert first != second


def test_the_same_facebook_account_may_serve_another_organization(owner, sim, make_client):
    agency = make_client()
    agency.signup("meta-agency@example.com")
    agency.org = agency.create_org("Agency")["id"]
    assert _connect(owner, sim)["status"] == "connected"
    result = _connect(agency, sim)
    assert result["status"] == "connected", result  # Q-4-11


# ------------------------------------------------------------------ disconnect
def test_disconnect_removes_the_permission_at_meta(owner, sim, admin_engine):
    conn = _connect(owner, sim)["connection_id"]
    (long_token,) = [t for t, v in sim.tokens.items() if v[2]]
    response = owner.post(f"/organizations/{owner.org}/connections/{conn}/disconnect")
    assert response.json()["data"]["status"] == "revoked"
    (removal,) = [r for r in sim.calls("/me/permissions") if r.method == "DELETE"]
    assert removal.headers["authorization"] == f"Bearer {long_token}"
    assert long_token in sim.removed and long_token not in sim.tokens
    (row,) = _rows(admin_engine, "SELECT ciphertext FROM external_connection_credentials")
    assert row["ciphertext"] is None
    actions = [r["action"] for r in _rows(admin_engine, "SELECT action FROM audit_logs")]
    assert "connection.revoked" in actions


def test_disconnect_still_works_when_meta_is_unreachable(owner, sim, admin_engine):
    conn = _connect(owner, sim)["connection_id"]
    original = sim.handler
    sim.handler = lambda request: (
        httpx.Response(503) if request.url.path.endswith("/me/permissions") else original(request)
    )
    response = owner.post(f"/organizations/{owner.org}/connections/{conn}/disconnect")
    assert response.json()["data"]["status"] == "revoked"
    (row,) = _rows(admin_engine, "SELECT ciphertext FROM external_connection_credentials")
    assert row["ciphertext"] is None  # our copy is deleted regardless
