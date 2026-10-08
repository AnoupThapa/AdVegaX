"""Fake-platform journey: connect → discover → link → sync → unlink → relink → disconnect (A16)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from app.providers.base.types import ResourceDescriptor, ResourceKind
from app.providers.fake import provider as fake

from tests.helpers import connect_fake, connected


@pytest.fixture
def owner(make_client):
    c = make_client()
    c.signup("conn-owner@example.com")
    c.org = c.create_org("Connected Co")["id"]
    return c


def _query(response):
    return parse_qs(urlsplit(response.headers["location"]).query)


def _resources(client, conn):
    return client.get(f"/organizations/{client.org}/connections/{conn}/resources").json()["data"]


def test_full_journey_with_audit_history(owner):
    org = owner.org
    conn = connected(owner, org)
    detail = owner.get(f"/organizations/{org}/connections/{conn}").json()["data"]
    assert detail["status"] == "active"
    assert detail["provider"] == "fake"
    assert detail["granted_scopes"] == ["read"]
    assert detail["account_label"] == "Fake Business"
    assert set(detail) == {
        "id",
        "provider",
        "auth_scheme",
        "status",
        "authorized_by_user_id",
        "granted_scopes",
        "account_label",
        "last_error_code",
        "created_at",
        "revoked_at",
    }

    resources = _resources(owner, conn)  # discovery ran as a background job after the callback
    assert {r["external_id"] for r in resources} == {
        "fake-acct-101",
        "fake-acct-102",
        "fake-store-1",
    }
    assert all(not r["linked"] for r in resources)  # discovery never links anything
    account = next(r for r in resources if r["external_id"] == "fake-acct-101")
    assert account["capabilities"]["product_cost"] is False  # declared, not assumed

    rid = account["id"]
    assert owner.post(f"/organizations/{org}/resources/{rid}/link").status_code == 201
    again = owner.post(f"/organizations/{org}/resources/{rid}/link")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ALREADY_LINKED"

    job = owner.post(f"/organizations/{org}/resources/{rid}/sync").json()["data"]
    status = owner.get(f"/organizations/{org}/jobs/{job['id']}").json()["data"]
    assert status["status"] == "succeeded"
    assert next(r for r in _resources(owner, conn) if r["id"] == rid)["last_synced_at"]

    assert owner.post(f"/organizations/{org}/resources/{rid}/unlink").status_code == 200
    assert (
        owner.post(f"/organizations/{org}/resources/{rid}/unlink").json()["error"]["code"]
        == "NOT_LINKED"
    )
    assert owner.post(f"/organizations/{org}/resources/{rid}/sync").status_code == 409
    assert owner.post(f"/organizations/{org}/resources/{rid}/link").status_code == 201
    history = owner.get(f"/organizations/{org}/resources/{rid}/links").json()["data"]
    assert [h["status"] for h in history] == ["unlinked", "active"]
    assert history[0]["unlink_reason"] == "user"

    disconnected = owner.post(f"/organizations/{org}/connections/{conn}/disconnect").json()["data"]
    assert disconnected["status"] == "revoked"
    assert "revoke" in fake.behaviour.calls
    assert owner.post(f"/organizations/{org}/connections/{conn}/disconnect").status_code == 200
    history = owner.get(f"/organizations/{org}/resources/{rid}/links").json()["data"]
    assert history[-1]["unlink_reason"] == "connection_revoked"
    assert (
        owner.post(f"/organizations/{org}/resources/{rid}/link").json()["error"]["code"]
        == "CONNECTION_NOT_ACTIVE"
    )
    assert owner.post(f"/organizations/{org}/connections/{conn}/rediscover").status_code == 409

    actions = [
        e["action"]
        for e in owner.get(f"/organizations/{org}/audit-logs", params={"page_size": 100}).json()[
            "data"
        ]
    ]
    for expected in (
        "connection.authorization_started",
        "connection.created",
        "connection.discovered",
        "resource.linked",
        "resource.sync_requested",
        "resource.synced",
        "resource.unlinked",
        "connection.revoked",
    ):
        assert expected in actions, expected


def test_rediscovery_marks_missing_resources_and_ends_links(owner):
    org = owner.org
    conn = connected(owner, org)
    store = next(r for r in _resources(owner, conn) if r["kind"] == "store")
    owner.post(f"/organizations/{org}/resources/{store['id']}/link")
    fake.behaviour.resources = [r for r in fake.behaviour.resources if r.kind != ResourceKind.STORE]
    fake.behaviour.resources.append(ResourceDescriptor(ResourceKind.AD_ACCOUNT, "fake-acct-103"))
    job = owner.post(f"/organizations/{org}/connections/{conn}/rediscover")
    assert job.status_code == 202
    after = {r["external_id"]: r for r in _resources(owner, conn)}
    assert after["fake-store-1"]["accessible"] is False
    assert after["fake-store-1"]["linked"] is False
    assert "fake-acct-103" in after
    link = owner.post(f"/organizations/{org}/resources/{store['id']}/link")
    assert link.json()["error"]["code"] == "RESOURCE_NOT_LINKABLE"
    history = owner.get(f"/organizations/{org}/resources/{store['id']}/links").json()["data"]
    assert history[-1]["unlink_reason"] == "resource_inaccessible"


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda q: {**q, "state": "x" * 43}, "invalid_state"),
        (lambda q: {k: v for k, v in q.items() if k != "state"}, "invalid_state"),
        (lambda q: {**q, "code": "approved.wrong-challenge"}, "invalid_request"),
        (lambda q: {**q, "code": "denied"}, "invalid_request"),
    ],
)
def test_callback_rejections(owner, mutate, code):
    started = owner.post(f"/organizations/{owner.org}/connections/fake/start").json()["data"]
    query = {k: v[0] for k, v in parse_qs(urlsplit(started["authorize_url"]).query).items()}
    params = mutate({"state": query["state"], "code": "approved." + query["code_challenge"]})
    response = owner.http.get(
        "/api/v1/connections/fake/callback", params=params, follow_redirects=False
    )
    assert response.status_code == 303
    assert _query(response)["code"] == [code]
    assert owner.get(f"/organizations/{owner.org}/connections").json()["data"] == []


def test_state_is_single_use_and_bound_to_user_and_provider(owner, make_client, runtime):
    started = owner.post(f"/organizations/{owner.org}/connections/fake/start").json()["data"]
    assert started["expires_in_seconds"] == 600
    query = {k: v[0] for k, v in parse_qs(urlsplit(started["authorize_url"]).query).items()}
    params = {"state": query["state"], "code": "approved." + query["code_challenge"]}

    other = make_client()
    other.signup("intruder@example.com")
    stolen = other.http.get(
        "/api/v1/connections/fake/callback", params=params, follow_redirects=False
    )
    assert _query(stolen)["code"] == ["session_mismatch"]
    # the state was consumed by the failed attempt: it cannot be replayed by anyone
    replay = owner.http.get(
        "/api/v1/connections/fake/callback", params=params, follow_redirects=False
    )
    assert _query(replay)["code"] == ["invalid_state"]

    started = owner.post(f"/organizations/{owner.org}/connections/fake/start").json()["data"]
    query = {k: v[0] for k, v in parse_qs(urlsplit(started["authorize_url"]).query).items()}
    anon = make_client()
    no_session = anon.http.get(
        "/api/v1/connections/fake/callback",
        params={"state": query["state"], "code": "x"},
        follow_redirects=False,
    )
    assert _query(no_session)["code"] == ["session_mismatch"]

    runtime.providers._providers["other"] = runtime.providers.get("fake")  # second provider code
    started = owner.post(f"/organizations/{owner.org}/connections/fake/start").json()["data"]
    query = {k: v[0] for k, v in parse_qs(urlsplit(started["authorize_url"]).query).items()}
    wrong = owner.http.get(
        "/api/v1/connections/other/callback",
        params={"state": query["state"], "code": "x"},
        follow_redirects=False,
    )
    assert _query(wrong)["code"] == ["invalid_state"]


def test_expired_state(owner, runtime):
    started = owner.post(f"/organizations/{owner.org}/connections/fake/start").json()["data"]
    query = {k: v[0] for k, v in parse_qs(urlsplit(started["authorize_url"]).query).items()}
    for key in runtime.redis.scan_iter("connect-state:*"):
        runtime.redis.delete(key)  # what Redis TTL expiry does
    response = owner.http.get(
        "/api/v1/connections/fake/callback",
        params={"state": query["state"], "code": "x"},
        follow_redirects=False,
    )
    assert _query(response)["code"] == ["invalid_state"]


def test_user_cancelled_and_permission_lost_mid_flow(owner, make_client):
    cancelled = connect_fake(owner, owner.org, approve=False)
    assert _query(cancelled)["status"] == ["cancelled"]

    manager = make_client()
    manager.signup("mgr@example.com")
    member_id = owner.invite_and_join(owner.org, manager, "mgr@example.com", "manager")
    started = manager.post(f"/organizations/{owner.org}/connections/fake/start").json()["data"]
    owner.patch(f"/organizations/{owner.org}/members/{member_id}", {"role": "viewer"})
    query = {k: v[0] for k, v in parse_qs(urlsplit(started["authorize_url"]).query).items()}
    response = manager.http.get(
        "/api/v1/connections/fake/callback",
        params={"state": query["state"], "code": "approved." + query["code_challenge"]},
        follow_redirects=False,
    )
    assert _query(response)["code"] == ["not_permitted"]


def test_roles_view_versus_manage_and_denials_are_audited(owner, make_client):
    org = owner.org
    conn = connected(owner, org)
    rid = _resources(owner, conn)[0]["id"]
    viewer = make_client()
    viewer.signup("viewer@example.com")
    owner.invite_and_join(org, viewer, "viewer@example.com", "viewer")
    assert viewer.get(f"/organizations/{org}/connections").status_code == 200
    assert viewer.get(f"/organizations/{org}/connections/{conn}/resources").status_code == 200
    for path in (
        "/connections/fake/start",
        f"/connections/{conn}/disconnect",
        f"/connections/{conn}/rediscover",
        f"/resources/{rid}/link",
        f"/resources/{rid}/sync",
    ):
        response = viewer.post(f"/organizations/{org}{path}")
        assert response.status_code == 403, path
    denials = owner.get(
        f"/organizations/{org}/audit-logs",
        params={"action": "authorization.denied", "page_size": 100},
    ).json()
    assert denials["meta"]["total"] == 5
    assert all(d["result"] == "denied" for d in denials["data"])
    assert denials["data"][0]["metadata"]["permission"] == "connections.manage"


def test_unknown_provider(owner):
    response = owner.post(f"/organizations/{owner.org}/connections/shopify/start")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNKNOWN_PROVIDER"


def test_auth_failure_during_sync_marks_connection_expired(owner):
    org = owner.org
    conn = connected(owner, org)
    rid = _resources(owner, conn)[0]["id"]
    owner.post(f"/organizations/{org}/resources/{rid}/link")
    fake.behaviour.auth_expired = True
    job = owner.post(f"/organizations/{org}/resources/{rid}/sync").json()["data"]
    status = owner.get(f"/organizations/{org}/jobs/{job['id']}").json()["data"]
    assert (status["status"], status["last_error_code"]) == ("failed", "auth_expired")
    connection = owner.get(f"/organizations/{org}/connections/{conn}").json()["data"]
    assert (connection["status"], connection["last_error_code"]) == ("expired", "auth_expired")
    assert owner.post(f"/organizations/{org}/resources/{rid}/sync").status_code == 409
    _assert_health_audit(owner, conn, status="expired", error="auth_expired")


def test_permission_denied_marks_connection_error(owner):
    fake.behaviour.permission_denied = True
    conn = connected(owner, owner.org)
    connection = owner.get(f"/organizations/{owner.org}/connections/{conn}").json()["data"]
    assert connection["status"] == "error"
    assert _resources(owner, conn) == []
    _assert_health_audit(owner, conn, status="error", error="permission_denied")


def _assert_health_audit(owner, conn, *, status, error):
    """Health changes are audited by the worker with codes only (no provider messages)."""
    logs = owner.get(
        f"/organizations/{owner.org}/audit-logs",
        params={"action": "connection.health_changed", "page_size": 100},
    ).json()["data"]
    entries = [e for e in logs if e["resource_id"] == conn]
    assert len(entries) == 1
    entry = entries[0]
    assert (entry["actor_type"], entry["actor_user_id"]) == ("worker", None)
    assert (entry["resource_type"], entry["result"]) == ("connection", "success")
    assert entry["after"] == {"status": status, "error": error}
    assert "fake-at-" not in str(entry) and "fake-rt-" not in str(entry)


def test_disconnect_survives_provider_revoke_failure(owner):
    conn = connected(owner, owner.org)
    fake.behaviour.revoke_fails = True
    response = owner.post(f"/organizations/{owner.org}/connections/{conn}/disconnect")
    assert response.json()["data"]["status"] == "revoked"
    logs = owner.get(
        f"/organizations/{owner.org}/audit-logs", params={"action": "connection.revoked"}
    ).json()["data"]
    assert logs[0]["metadata"]["revoked_at_provider"] is False


def test_connections_are_isolated_per_organization(owner, make_client):
    """The same external account in two organizations needs a connection in each (A16)."""
    other = make_client()
    other.signup("second-org@example.com")
    other.org = other.create_org("Second Org")["id"]
    a = connected(owner, owner.org)
    b = connected(other, other.org)
    assert a != b
    ids_a = {r["id"] for r in _resources(owner, a)}
    ids_b = {r["id"] for r in _resources(other, b)}
    assert ids_a.isdisjoint(ids_b)
    assert [
        c["id"] for c in other.get(f"/organizations/{other.org}/connections").json()["data"]
    ] == [b]
