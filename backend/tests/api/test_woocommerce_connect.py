"""Connecting a WooCommerce store (task 2B-04, PHASE_02B_PLAN §6).

The merchant approves read-only access on their own store; the store posts the generated key
to AdVegaX server to server; the browser comes back and sees the result. Everything runs
through the real API, database, job runner and the WooCommerce simulator.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from app.providers.base.registry import build_registry
from app.providers.woocommerce.provider import store_timezone
from sqlalchemy import text

from tests.woocommerce_sim import WooSim, approve, build_provider

HOST = "shop.example.com"


@pytest.fixture
def sim(runtime):
    s = WooSim()
    s.add_store(HOST, path="/store")
    runtime.providers.register(build_provider(s))
    return s


@pytest.fixture
def owner(make_client, sim):
    c = make_client()
    c.signup("woo-owner@example.com")
    c.org = c.create_org("Woo Co")["id"]
    return c


@pytest.fixture
def platform(make_client):
    """The store's server: posts to AdVegaX without any session or CSRF token."""
    return make_client().http


def _start(c, url=f"https://{HOST}/store/"):
    return c.post(
        f"/organizations/{c.org}/connections/woocommerce/start", {"params": {"store_url": url}}
    )


def _redirect(response):
    assert response.status_code == 303, response.text
    location = urlsplit(response.headers["location"])
    assert location.path == "/connections"
    return {k: v[0] for k, v in parse_qs(location.query).items()}


def _connect(c, platform, sim, **kw):
    started = _start(c)
    assert started.status_code == 200, started.text
    return approve(platform, c.http, sim, started.json()["data"]["authorize_url"], **kw)


def _rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return db.execute(text(sql), params).mappings().all()


# ------------------------------------------------------------------ the happy path
def test_connect_with_a_read_only_key_and_discover_the_store(owner, platform, sim, admin_engine):
    started = _start(owner).json()["data"]
    url = urlsplit(started["authorize_url"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert (url.scheme, url.hostname, url.path) == ("https", HOST, "/store/wc-auth/v1/authorize")
    assert (query["scope"], query["app_name"]) == ("read", "AdVegaX")
    assert query["callback_url"].endswith("/api/v1/connections/woocommerce/credentials")
    assert query["return_url"].endswith("/api/v1/connections/woocommerce/callback")
    # The address was checked first, with the public index only — no key exists yet.
    (preflight,) = sim.requests
    assert preflight.url.path == "/store/wp-json/" and "authorization" not in preflight.headers

    approval, returned = approve(platform, owner.http, sim, started["authorize_url"])
    assert approval.delivery.status_code == 200
    assert approval.delivery.json()["data"] == {"status": "accepted"}  # nothing echoed
    result = _redirect(returned)
    assert (result["status"], result["organization_id"]) == ("connected", owner.org)

    conn = owner.get(f"/organizations/{owner.org}/connections/{result['connection_id']}").json()[
        "data"
    ]
    assert (conn["provider"], conn["auth_scheme"], conn["status"]) == (
        "woocommerce",
        "api_key",
        "active",
    )
    assert conn["granted_scopes"] == ["read"]
    assert conn["account_label"] == "Mediflex Test"
    (resource,) = owner.get(
        f"/organizations/{owner.org}/connections/{conn['id']}/resources"
    ).json()["data"]
    assert (resource["kind"], resource["external_id"]) == ("store", f"{HOST}/store")
    assert (resource["currency"], resource["timezone"]) == ("AUD", "Australia/Sydney")

    ck, cs = approval.key
    (row,) = _rows(admin_engine, "SELECT ciphertext FROM external_connection_credentials")
    assert ck.encode() not in bytes(row["ciphertext"]) and cs.encode() not in bytes(
        row["ciphertext"]
    )
    (stored,) = _rows(admin_engine, "SELECT external_account_id FROM external_connections")
    assert stored["external_account_id"] == f"{HOST}/store"
    # The key was verified against the store recorded at start, with Basic auth.
    status_call = sim.calls("/wc/v3/system_status")[0]
    assert status_call.headers["host"] == HOST and status_call.headers["authorization"]
    assert ck not in str(status_call.url)
    audit = [r["action"] for r in _rows(admin_engine, "SELECT action FROM audit_logs")]
    assert "connection.created" in audit
    for text_ in (str(_rows(admin_engine, "SELECT * FROM audit_logs")), returned.text):
        assert ck not in text_ and cs not in text_


# ------------------------------------------------------------------ start
@pytest.mark.parametrize(
    "url", ["http://shop.example.com", "https://localhost", "https://10.0.0.1", "not a url!"]
)
def test_invalid_addresses_are_refused_before_anything_is_called(owner, sim, url):
    response = _start(owner, url)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CONNECT_PARAMS"
    assert sim.requests == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"status": 503}, "retryable"),
        ({"woocommerce": False}, "woocommerce_api_not_found"),
    ],
)
def test_a_store_that_cannot_be_used_is_reported_at_start(owner, sim, change, reason):
    for key, value in change.items():
        setattr(sim.stores[HOST], key, value)
    response = _start(owner)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "STORE_NOT_REACHABLE"
    assert error["details"] == [{"reason": reason}]


def test_viewers_cannot_start(owner, make_client, sim):
    viewer = make_client()
    viewer.signup("woo-viewer@example.com")
    owner.invite_and_join(owner.org, viewer, "woo-viewer@example.com", "viewer")
    viewer.org = owner.org
    assert _start(viewer).status_code == 403


# ------------------------------------------------------------------ key delivery
def test_a_key_with_more_than_read_access_is_refused_and_not_stored(
    owner, platform, sim, admin_engine
):
    approval, returned = _connect(owner, platform, sim, permissions="read_write")
    assert approval.delivery.status_code == 422
    assert approval.delivery.json()["error"]["code"] == "INVALID_KEY_DELIVERY"
    result = _redirect(returned)
    assert (result["status"], result["code"]) == ("error", "not_read_only")
    assert _rows(admin_engine, "SELECT id FROM external_connections") == []


def test_a_key_is_verified_on_the_store_recorded_at_start(owner, platform, sim, admin_engine):
    """A key for another store (e.g. an attacker's) does not work on the recorded store."""
    sim.add_store("attacker.example")
    approval, returned = _connect(owner, platform, sim, key_from="attacker.example")
    assert approval.delivery.status_code == 422
    assert _redirect(returned)["code"] == "key_rejected"
    assert sim.calls("/wc/v3/system_status")[0].headers["host"] == HOST
    assert _rows(admin_engine, "SELECT id FROM external_connections") == []


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"version": "8.9.3"}, "woocommerce_too_old"),
        ({"strips_auth": True}, "auth_header_stripped"),
    ],
)
def test_unusable_stores_are_explained(owner, platform, sim, change, code):
    for key, value in change.items():
        setattr(sim.stores[HOST], key, value)
    approval, returned = _connect(owner, platform, sim)
    assert approval.delivery.status_code == 422
    assert _redirect(returned)["code"] == code


def test_each_connect_state_works_once(owner, platform, sim):
    approval, _ = _connect(owner, platform, sim)
    ck, cs = sim.issue_key(HOST)
    again = platform.post(
        approval.callback_path,
        json={
            "user_id": approval.user_id,
            "consumer_key": ck,
            "consumer_secret": cs,
            "key_permissions": "read",
        },
    )
    assert again.status_code == 422
    connections = owner.get(f"/organizations/{owner.org}/connections").json()["data"]
    assert len(connections) == 1


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[1, 2]",
        b'{"user_id": "unknown-state", "consumer_key": "ck_x", "consumer_secret": "cs_x"}',
        b'{"consumer_key": "ck_0123456789012345678901"}',
    ],
)
def test_malformed_or_unknown_deliveries_are_refused(platform, sim, body):
    response = platform.post(
        "/api/v1/connections/woocommerce/credentials",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_KEY_DELIVERY"
    assert "ck_" not in response.text


def test_oversized_deliveries_are_refused(platform, sim):
    response = platform.post(
        "/api/v1/connections/woocommerce/credentials",
        content=b'{"user_id": "' + b"x" * 5000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_platforms_without_key_delivery_refuse_it(platform):
    for provider in ("fake", "shopify", "nope"):
        response = platform.post(f"/api/v1/connections/{provider}/credentials", json={})
        assert response.status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/connections/woocommerce/credentials/x",
        "/api/v1/connections/woocommerce/start",
        "/api/v1/connections/woo-commerce/credentials",
    ],
)
def test_the_csrf_exemption_is_exactly_the_delivery_path(platform, path):
    response = platform.post(path, json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


def test_deliveries_are_rate_limited_per_address(runtime, platform, sim):
    limit = runtime.settings.THROTTLE_KEY_DELIVERY_PER_IP_PER_MINUTE
    codes = [
        platform.post("/api/v1/connections/woocommerce/credentials", json={}).status_code
        for _ in range(limit + 1)
    ]
    assert codes[:limit] == [422] * limit
    assert codes[-1] == 429


# ------------------------------------------------------------------ the browser's return
def test_a_merchant_who_declines_sees_cancelled_and_the_state_is_retired(owner, platform, sim):
    approval, returned = _connect(owner, platform, sim, success=False)
    assert approval.delivery is None
    assert _redirect(returned) == {"status": "cancelled", "organization_id": owner.org}
    ck, cs = sim.issue_key(HOST)
    late = platform.post(
        approval.callback_path,
        json={
            "user_id": approval.user_id,
            "consumer_key": ck,
            "consumer_secret": cs,
            "key_permissions": "read",
        },
    )
    assert late.status_code == 422


def test_a_return_without_delivery_says_so(owner, platform, sim):
    _, returned = _connect(owner, platform, sim, deliver=False)
    assert _redirect(returned)["code"] == "key_not_delivered"


def test_another_browser_cannot_read_the_result(owner, platform, sim, make_client):
    started = _start(owner).json()["data"]["authorize_url"]
    other = make_client()
    other.signup("woo-other@example.com")
    _, returned = approve(platform, other.http, sim, started)
    result = _redirect(returned)
    assert result == {"status": "error", "code": "session_mismatch"}  # no organization shown


def test_unknown_return_tokens_are_refused(owner):
    response = owner.http.get(
        "/api/v1/connections/woocommerce/callback",
        params={"success": "1", "user_id": "nope"},
        follow_redirects=False,
    )
    assert _redirect(response) == {"status": "error", "code": "invalid_state"}


# ------------------------------------------------------------------ organizations
def test_one_store_one_organization(owner, platform, sim, make_client):
    _connect(owner, platform, sim)
    other = make_client()
    other.signup("woo-second@example.com")
    other.org = other.create_org("Second Co")["id"]
    response = _start(other, f"https://{HOST.upper()}/Store")  # same store, other spelling
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACCOUNT_IN_USE"


def test_a_store_connected_elsewhere_meanwhile_is_refused_at_delivery(
    owner, platform, sim, make_client
):
    other = make_client()
    other.signup("woo-racer@example.com")
    other.org = other.create_org("Racer Co")["id"]
    slow = _start(owner).json()["data"]["authorize_url"]
    _connect(other, platform, sim)  # the other organization finishes first
    approval, returned = approve(platform, owner.http, sim, slow)
    assert approval.delivery.status_code == 422
    assert _redirect(returned)["code"] == "account_in_use"


def test_reconnect_reuses_the_connection(owner, platform, sim):
    _, first = _connect(owner, platform, sim)
    _, second = _connect(owner, platform, sim)
    assert _redirect(first)["connection_id"] == _redirect(second)["connection_id"]
    assert len(owner.get(f"/organizations/{owner.org}/connections").json()["data"]) == 1


def test_a_person_who_lost_the_role_meanwhile_cannot_finish(owner, platform, sim, make_client):
    manager = make_client()
    manager.signup("woo-manager@example.com")
    owner.invite_and_join(owner.org, manager, "woo-manager@example.com", "manager")
    manager.org = owner.org
    started = _start(manager).json()["data"]["authorize_url"]
    (member,) = [
        m
        for m in owner.get(f"/organizations/{owner.org}/members").json()["data"]
        if m["email"] == "woo-manager@example.com"
    ]
    changed = owner.patch(f"/organizations/{owner.org}/members/{member['id']}", {"role": "viewer"})
    assert changed.status_code == 200, changed.text
    approval, returned = approve(platform, manager.http, sim, started)
    assert approval.delivery.status_code == 422
    assert _redirect(returned)["code"] == "not_permitted"


def test_disconnect_deletes_the_key_and_calls_nothing(owner, platform, sim, admin_engine):
    _, returned = _connect(owner, platform, sim)
    conn = _redirect(returned)["connection_id"]
    before = len(sim.requests)
    response = owner.post(f"/organizations/{owner.org}/connections/{conn}/disconnect")
    assert response.json()["data"]["status"] == "revoked"
    assert len(sim.requests) == before  # a read-only key cannot revoke itself
    (row,) = _rows(admin_engine, "SELECT ciphertext FROM external_connection_credentials")
    assert row["ciphertext"] is None


# ------------------------------------------------------------------ configuration
def test_woocommerce_is_offered_only_when_switched_on(settings):
    from app.runtime import outbound_policy

    off = build_registry(settings, outbound=outbound_policy(settings))
    assert "woocommerce" not in off.codes()
    on = build_registry(
        settings.model_copy(update={"WOOCOMMERCE_ENABLED": True}),
        outbound=outbound_policy(settings),
    )
    assert "woocommerce" in on.codes()


@pytest.mark.parametrize(
    ("zone", "offset", "expected"),
    [
        ("Australia/Sydney", "10", "Australia/Sydney"),
        ("", "10", "Etc/GMT-10"),
        ("", "-5", "Etc/GMT+5"),
        ("", "0", "UTC"),
        ("", "5.5", None),  # no IANA zone for a manual half-hour offset
        ("Not/AZone", "x", None),
        (None, None, None),
        ("", "99", None),
    ],
)
def test_store_time_zone(zone, offset, expected):
    assert store_timezone(zone, offset) == expected
