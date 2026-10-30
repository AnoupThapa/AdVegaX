"""Google Analytics connect through the real API, database and job runner (task 5-03, PLAN §6).

Start → Google's consent screen (simulated, PKCE + offline access, ``analytics.readonly`` only)
→ callback → encrypted tokens → refresh before expiry → a refused refresh means "Needs
reconnecting" → reconnect by the same Google account reuses the connection → Google Ads and
Google Analytics with the same Google account stay two separate connections (Q-5-2) →
disconnect revokes the permission at Google. No token or secret ever appears in a response,
the audit log or the logs.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.integrations.tokens import usable_secrets
from app.providers.base.errors import AuthExpiredError
from app.providers.base.registry import build_registry
from pydantic import SecretStr
from sqlalchemy import text

from tests.ga4_sim import ANALYTICS_SCOPE, GA4Sim, build_provider
from tests.google_oauth_sim import CLIENT_ID, CLIENT_SECRET

SUB = "108000000000000000001"


@pytest.fixture
def sim(runtime, clock):
    s = GA4Sim(clock=clock)
    s.add_property("111", "900", SUB, display_name="Eve Zone AU")
    runtime.providers.register(build_provider(s))
    return s


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup("ga-owner@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    return c


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def _start(client, provider="google_analytics", params=None):
    return client.post(
        f"/organizations/{client.org}/connections/{provider}/start", {"params": params or {}}
    )


def _callback(client, params, provider="google_analytics"):
    response = client.http.get(
        f"/api/v1/connections/{provider}/callback", params=params, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


def _connect(client, sim, sub=SUB, provider="google_analytics", **approve):
    started = _start(client, provider)
    assert started.status_code == 200, started.text
    return _callback(
        client, sim.approve(started.json()["data"]["authorize_url"], sub, **approve), provider
    )


# ------------------------------------------------------------------ offered and started
def test_google_analytics_is_offered_only_when_switched_on_and_configured(settings):
    def codes(**changes):
        return build_registry(settings.model_copy(update=changes), outbound=object()).codes()

    assert "google_analytics" not in codes()
    assert "google_analytics" not in codes(GOOGLE_ANALYTICS_ENABLED=True)  # no OAuth client
    complete = {
        "GOOGLE_ANALYTICS_ENABLED": True,
        "GOOGLE_ADS_CLIENT_ID": CLIENT_ID,
        "GOOGLE_ADS_CLIENT_SECRET": SecretStr(CLIENT_SECRET),
    }
    assert "google_analytics" in codes(**complete)  # no developer token needed
    assert "google_ads" not in codes(**complete)  # each product is switched on alone
    assert "google_analytics" not in codes(**{**complete, "GOOGLE_ANALYTICS_ENABLED": False})


def test_it_is_listed_as_analytics_without_write_capabilities(owner):
    found = {p["code"]: p for p in owner.get("/providers").json()["data"]}["google_analytics"]
    assert (found["display_name"], found["category"], found["test_only"]) == (
        "Google Analytics",
        "analytics",
        False,
    )
    caps = found["capabilities"]
    assert caps["pkce"] and caps["token_refresh"] and caps["token_revocation"]
    assert not caps["create_campaign"] and not caps["validate_only"]


def test_start_asks_google_only_for_analytics_readonly(owner):
    started = _start(owner)
    assert started.status_code == 200
    url = urlsplit(started.json()["data"]["authorize_url"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert (url.hostname, url.path) == ("accounts.google.com", "/o/oauth2/v2/auth")
    assert query["scope"] == f"{ANALYTICS_SCOPE} openid"
    assert query["redirect_uri"].endswith("/api/v1/connections/google_analytics/callback")
    assert (query["access_type"], query["code_challenge_method"]) == ("offline", "S256")
    assert CLIENT_SECRET not in started.text


def test_nothing_is_typed_and_viewers_cannot_start(owner, make_client):
    response = _start(owner, params={"property": "111"})
    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "INVALID_CONNECT_PARAMS",
    )
    viewer = make_client()
    viewer.signup("ga-viewer@example.com")
    owner.invite_and_join(owner.org, viewer, "ga-viewer@example.com", "viewer")
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
        "google_analytics",
        "Google Analytics",
        "active",
    )
    assert data["sign_in_expires_at"] is None  # renews itself: no end date to show
    (row,) = _rows(
        admin_engine,
        "SELECT c.external_account_id, c.granted_scopes, k.ciphertext, k.token_expires_at "
        "FROM external_connections c JOIN external_connection_credentials k "
        "ON k.connection_id = c.id",
    )
    assert row["external_account_id"] == f"{owner.org}:{SUB}"
    assert ANALYTICS_SCOPE in row["granted_scopes"]
    tokens = [*sim.refresh_tokens, *sim.access_tokens]
    audit = json.dumps(_rows(admin_engine, "SELECT * FROM audit_logs"), default=str)
    logs = [r.getMessage() for r in caplog.records if "http://testserver" not in r.getMessage()]
    for secret in (*tokens, CLIENT_SECRET):
        assert secret not in detail.text and secret not in audit
        assert secret.encode() not in bytes(row["ciphertext"])
        assert all(secret not in line for line in logs)


def test_declining_or_unticking_analytics_connects_nothing(owner, sim, admin_engine):
    assert _connect(owner, sim, declined=True)["status"] == "cancelled"
    result = _connect(owner, sim, scopes="openid")
    assert (result["status"], result["code"]) == ("error", "missing_scopes")
    assert sim.calls("/token") == []
    assert _rows(admin_engine, "SELECT id FROM external_connections") == []


def test_a_code_google_refuses_connects_nothing(owner, sim):
    started = _start(owner)
    params = sim.approve(started.json()["data"]["authorize_url"], SUB)
    sim._codes.clear()
    result = _callback(owner, params)
    assert (result["status"], result["code"]) == ("error", "google_sign_in_rejected")


# ------------------------------------------------------------------ token lifecycle
def test_tokens_are_refreshed_before_they_expire(owner, sim, runtime, clock, admin_engine):
    conn = uuid.UUID(_connect(owner, sim)["connection_id"])
    org = uuid.UUID(owner.org)
    first = usable_secrets(runtime, org, conn)
    clock.advance(timedelta(minutes=58))
    second = usable_secrets(runtime, org, conn)
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] == first["refresh_token"]
    (row,) = _rows(admin_engine, "SELECT granted_scopes FROM external_connections")
    assert ANALYTICS_SCOPE in row["granted_scopes"]


def test_a_refused_refresh_means_needs_reconnecting(owner, sim, runtime, clock):
    conn = _connect(owner, sim)["connection_id"]
    sim.refresh_tokens.clear()  # the person removed AdVegaX in their Google account
    clock.advance(timedelta(minutes=58))
    with pytest.raises(AuthExpiredError):
        usable_secrets(runtime, uuid.UUID(owner.org), uuid.UUID(conn))
    detail = owner.get(f"/organizations/{owner.org}/connections/{conn}").json()["data"]
    assert (detail["status"], detail["last_error_code"]) == ("expired", "google_sign_in_rejected")


# ------------------------------------------------------------------ reconnect and products
def test_reconnecting_with_the_same_google_account_reuses_the_connection(owner, sim):
    first = _connect(owner, sim)["connection_id"]
    assert _connect(owner, sim)["connection_id"] == first
    assert len(owner.get(f"/organizations/{owner.org}/connections").json()["data"]) == 1


def test_google_ads_and_analytics_stay_separate_connections(owner, sim, runtime, clock):
    from tests.google_ads_sim import GoogleAdsSim
    from tests.google_ads_sim import build_provider as build_ads

    ads = GoogleAdsSim(clock=clock)
    ads.add_user(SUB)
    ads_provider = build_ads(ads)
    ads_provider.discover_resources = lambda secrets: []
    runtime.providers.register(ads_provider)
    analytics = _connect(owner, sim)["connection_id"]
    google_ads = _connect(owner, ads, provider="google_ads")["connection_id"]
    assert analytics != google_ads  # one Google account, two permissions, two connections
    listed = {
        c["provider"] for c in owner.get(f"/organizations/{owner.org}/connections").json()["data"]
    }
    assert listed == {"google_analytics", "google_ads"}
    disconnected = owner.post(f"/organizations/{owner.org}/connections/{analytics}/disconnect")
    assert disconnected.json()["data"]["status"] == "revoked"
    other = owner.get(f"/organizations/{owner.org}/connections/{google_ads}").json()["data"]
    assert other["status"] == "active"  # removing one leaves the other


# ------------------------------------------------------------------ disconnect
def test_disconnect_revokes_the_permission_at_google(owner, sim, admin_engine):
    conn = _connect(owner, sim)["connection_id"]
    (refresh,) = sim.refresh_tokens
    response = owner.post(f"/organizations/{owner.org}/connections/{conn}/disconnect")
    assert response.json()["data"]["status"] == "revoked"
    (revoke,) = sim.calls("/revoke")
    assert parse_qs(revoke.content.decode())["token"] == [refresh]
    (row,) = _rows(admin_engine, "SELECT ciphertext FROM external_connection_credentials")
    assert row["ciphertext"] is None
