"""Google Ads connect through the real API, database and job runner (task 3-03, PLAN §6).

Start → Google's consent screen (simulated, PKCE + offline access) → callback → encrypted
tokens → refresh before expiry → a refused refresh means "Needs reconnecting" → reconnect by
the same Google account reuses the connection → the same Google account may also serve another
organization (Q-3-11) → disconnect revokes the permission at Google. No token or secret ever
appears in a response, the audit log or the logs.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from app.domains.integrations.tokens import usable_secrets
from app.providers.base.errors import AuthExpiredError
from app.providers.base.registry import build_registry
from pydantic import SecretStr
from sqlalchemy import text

from tests.google_ads_sim import (
    ADS_SCOPE,
    CLIENT_SECRET,
    DEVELOPER_TOKEN,
    GoogleAdsSim,
    build_provider,
    sample_hierarchy,
)

SUB = "108000000000000000001"


@pytest.fixture
def sim(runtime, clock):
    s = sample_hierarchy(GoogleAdsSim(clock=clock))
    provider = build_provider(s)
    provider.discover_resources = lambda secrets: []  # discovery is task 3-04
    runtime.providers.register(provider)
    return s


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup("ads-owner@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    return c


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def _start(client, params=None):
    return client.post(
        f"/organizations/{client.org}/connections/google_ads/start", {"params": params or {}}
    )


def _callback(client, params):
    response = client.http.get(
        "/api/v1/connections/google_ads/callback", params=params, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


def _connect(client, sim, sub=SUB, **approve):
    started = _start(client)
    assert started.status_code == 200, started.text
    return _callback(client, sim.approve(started.json()["data"]["authorize_url"], sub, **approve))


# ------------------------------------------------------------------ offered and started
def test_google_ads_is_offered_only_when_fully_configured(settings):
    def codes(**changes):
        return build_registry(settings.model_copy(update=changes), outbound=object()).codes()

    assert "google_ads" not in codes()
    assert "google_ads" not in codes(GOOGLE_ADS_ENABLED=True)  # no client or token
    complete = {
        "GOOGLE_ADS_ENABLED": True,
        "GOOGLE_ADS_CLIENT_ID": "id.apps.googleusercontent.com",
        "GOOGLE_ADS_CLIENT_SECRET": SecretStr("s"),
        "GOOGLE_ADS_DEVELOPER_TOKEN": SecretStr("d"),
    }
    assert "google_ads" in codes(**complete)
    assert "google_ads" not in codes(**{**complete, "GOOGLE_ADS_ENABLED": False})


def test_provider_is_listed_as_advertising_without_write_capabilities(owner):
    google = {p["code"]: p for p in owner.get("/providers").json()["data"]}["google_ads"]
    assert (google["display_name"], google["category"], google["test_only"]) == (
        "Google Ads",
        "advertising",
        False,
    )
    caps = google["capabilities"]
    assert caps["pkce"] and caps["token_refresh"] and caps["token_revocation"]
    assert not caps["create_campaign"] and not caps["validate_only"]


def test_start_sends_the_person_to_google_with_pkce_and_offline_access(owner, settings):
    started = _start(owner)
    assert started.status_code == 200
    url = urlsplit(started.json()["data"]["authorize_url"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert (url.scheme, url.hostname, url.path) == (
        "https",
        "accounts.google.com",
        "/o/oauth2/v2/auth",
    )
    assert query["scope"].split() == [ADS_SCOPE, "openid"]  # no email, profile or other Google data
    assert (query["access_type"], query["prompt"], query["response_type"]) == (
        "offline",
        "consent",
        "code",
    )
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) == 43
    assert query["redirect_uri"].endswith("/api/v1/connections/google_ads/callback")
    assert query["include_granted_scopes"] == "false"
    assert CLIENT_SECRET not in started.text and DEVELOPER_TOKEN not in started.text


def test_nothing_is_typed_for_google_ads(owner):
    response = _start(owner, {"shop_domain": "x"})
    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "INVALID_CONNECT_PARAMS",
    )


def test_viewers_cannot_start(owner, make_client):
    viewer = make_client()
    viewer.signup("ads-viewer@example.com")
    owner.invite_and_join(owner.org, viewer, "ads-viewer@example.com", "viewer")
    viewer.org = owner.org
    assert _start(viewer).status_code == 403


# ------------------------------------------------------------------ the callback
def test_connect_stores_encrypted_tokens_and_never_shows_them(owner, sim, admin_engine, caplog):
    caplog.set_level(logging.DEBUG)
    result = _connect(owner, sim)
    assert result["status"] == "connected", result
    conn = result["connection_id"]
    detail = owner.get(f"/organizations/{owner.org}/connections/{conn}")
    data = detail.json()["data"]
    assert (data["provider"], data["account_label"], data["status"]) == (
        "google_ads",
        "Google Ads",
        "active",
    )
    (exchange,) = sim.calls("/token")
    form = parse_qs(exchange.content.decode())
    assert form["grant_type"] == ["authorization_code"] and len(form["code_verifier"][0]) >= 43
    (row,) = _rows(
        admin_engine,
        "SELECT c.external_account_id, c.granted_scopes, k.ciphertext, k.token_expires_at "
        "FROM external_connections c JOIN external_connection_credentials k "
        "ON k.connection_id = c.id",
    )
    assert row["external_account_id"] == f"{owner.org}:{SUB}"
    assert ADS_SCOPE in row["granted_scopes"]
    assert row["token_expires_at"] is not None
    tokens = [*sim.refresh_tokens, *sim.access_tokens]
    audit = json.dumps(_rows(admin_engine, "SELECT * FROM audit_logs"), default=str)
    logs = [r.getMessage() for r in caplog.records if "http://testserver" not in r.getMessage()]
    for secret in (*tokens, CLIENT_SECRET, DEVELOPER_TOKEN):
        assert secret not in detail.text and secret not in audit
        assert secret.encode() not in bytes(row["ciphertext"])
        assert all(secret not in line for line in logs)


def test_declining_on_googles_page_connects_nothing(owner, sim, admin_engine):
    assert _connect(owner, sim, declined=True)["status"] == "cancelled"
    assert sim.calls("/token") == []
    assert _rows(admin_engine, "SELECT id FROM external_connections") == []


def test_unticking_google_ads_on_the_consent_screen_is_explained(owner, sim, admin_engine):
    result = _connect(owner, sim, scopes="openid")
    assert (result["status"], result["code"]) == ("error", "missing_scopes")
    assert sim.calls("/token") == []  # refused before any token is issued
    assert _rows(admin_engine, "SELECT id FROM external_connections") == []


def test_a_code_google_refuses_connects_nothing(owner, sim):
    started = _start(owner)
    params = sim.approve(started.json()["data"]["authorize_url"], SUB)
    sim._codes.clear()  # e.g. used twice or expired
    result = _callback(owner, params)
    assert (result["status"], result["code"]) == ("error", "google_sign_in_rejected")


def test_the_state_works_once_and_only_for_the_same_person(owner, sim, make_client):
    started = _start(owner)
    params = sim.approve(started.json()["data"]["authorize_url"], SUB)
    other = make_client()
    other.signup("someone-else@example.com")
    assert _callback(other, params)["code"] == "session_mismatch"
    assert _callback(owner, params)["code"] == "invalid_state"  # already consumed


# ------------------------------------------------------------------ token lifecycle
def test_tokens_are_refreshed_before_they_expire(owner, sim, runtime, clock):
    conn = uuid.UUID(_connect(owner, sim)["connection_id"])
    org = uuid.UUID(owner.org)
    first = usable_secrets(runtime, org, conn)
    assert len(sim.calls("/token")) == 1  # fresh: no refresh
    clock.advance(timedelta(minutes=58))
    second = usable_secrets(runtime, org, conn)
    (refresh,) = [r for r in sim.calls("/token") if b"grant_type=refresh_token" in r.content]
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] == first["refresh_token"]  # Google kept it
    assert refresh.content.count(b"client_secret=") == 1


def test_a_new_refresh_token_from_google_is_saved(owner, sim, runtime, clock):
    conn = uuid.UUID(_connect(owner, sim)["connection_id"])
    sim.send_new_refresh_on_refresh = True
    clock.advance(timedelta(minutes=58))
    secrets = usable_secrets(runtime, uuid.UUID(owner.org), conn)
    assert secrets["refresh_token"] in sim.refresh_tokens


def test_a_refused_refresh_means_needs_reconnecting(owner, sim, runtime, clock):
    conn = _connect(owner, sim)["connection_id"]
    sim.refresh_tokens.clear()  # the person removed AdVegaX in their Google account
    clock.advance(timedelta(minutes=58))
    with pytest.raises(AuthExpiredError):
        usable_secrets(runtime, uuid.UUID(owner.org), uuid.UUID(conn))
    detail = owner.get(f"/organizations/{owner.org}/connections/{conn}").json()["data"]
    assert (detail["status"], detail["last_error_code"]) == ("expired", "google_sign_in_rejected")


# ------------------------------------------------------------------ reconnect and sharing
def test_reconnecting_with_the_same_google_account_reuses_the_connection(
    owner, sim, runtime, clock
):
    first = _connect(owner, sim)["connection_id"]
    sim.refresh_tokens.clear()
    clock.advance(timedelta(minutes=58))
    with pytest.raises(AuthExpiredError):
        usable_secrets(runtime, uuid.UUID(owner.org), uuid.UUID(first))
    again = _connect(owner, sim)
    assert again["connection_id"] == first
    detail = owner.get(f"/organizations/{owner.org}/connections/{first}").json()["data"]
    assert (detail["status"], detail["last_error_code"]) == ("active", None)
    assert len(owner.get(f"/organizations/{owner.org}/connections").json()["data"]) == 1


def test_another_google_account_is_a_second_connection(owner, sim):
    sim.add_user("108000000000000000009", "1000000003")
    first = _connect(owner, sim)["connection_id"]
    second = _connect(owner, sim, sub="108000000000000000009")["connection_id"]
    assert first != second


def test_the_same_google_account_may_serve_another_organization(owner, sim, make_client):
    agency = make_client()
    agency.signup("agency@example.com")
    agency.org = agency.create_org("Agency")["id"]
    assert _connect(owner, sim)["status"] == "connected"
    result = _connect(agency, sim)
    assert result["status"] == "connected", result  # Q-3-11: no "already connected elsewhere"
    assert len(owner.get(f"/organizations/{owner.org}/connections").json()["data"]) == 1


# ------------------------------------------------------------------ disconnect
def test_disconnect_revokes_the_permission_at_google(owner, sim, admin_engine):
    conn = _connect(owner, sim)["connection_id"]
    (refresh,) = sim.refresh_tokens
    response = owner.post(f"/organizations/{owner.org}/connections/{conn}/disconnect")
    assert response.json()["data"]["status"] == "revoked"
    (revoke,) = sim.calls("/revoke")
    assert parse_qs(revoke.content.decode())["token"] == [refresh]
    assert sim.refresh_tokens == {} and refresh in sim.revoked
    (row,) = _rows(admin_engine, "SELECT ciphertext FROM external_connection_credentials")
    assert row["ciphertext"] is None
    actions = [r["action"] for r in _rows(admin_engine, "SELECT action FROM audit_logs")]
    assert "connection.revoked" in actions


def test_disconnect_still_works_when_google_is_unreachable(owner, sim, admin_engine):
    conn = _connect(owner, sim)["connection_id"]
    sim.token_status = None
    original = sim.handler
    sim.handler = lambda request: (
        httpx.Response(503) if request.url.path == "/revoke" else original(request)
    )
    response = owner.post(f"/organizations/{owner.org}/connections/{conn}/disconnect")
    assert response.json()["data"]["status"] == "revoked"
    (row,) = _rows(admin_engine, "SELECT ciphertext FROM external_connection_credentials")
    assert row["ciphertext"] is None  # our copy is deleted regardless
