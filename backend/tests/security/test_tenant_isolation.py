"""Cross-tenant isolation through the API (PHASE_01A_PLAN §16.1).

The route sweep is generated from the OpenAPI schema, so every new organization-scoped
route is covered automatically.
"""

from __future__ import annotations

import re

import pytest

from tests.helpers import last_email

BODIES = {
    ("patch", "/organizations/{organization_id}"): {"name": "Hijacked"},
    ("patch", "/organizations/{organization_id}/members/{member_id}"): {"role": "viewer"},
    ("post", "/organizations/{organization_id}/invitations"): {
        "email": "evil@example.com",
        "role": "owner",
    },
}


@pytest.fixture
def tenants(make_client):
    a, b = make_client(), make_client()
    a.signup("alice@tenant-a.com")
    b.signup("bob@tenant-b.com")
    org_a = a.create_org("Tenant A")["id"]
    org_b = b.create_org("Tenant B")["id"]
    inv_b = b.post(
        f"/organizations/{org_b}/invitations", {"email": "pending@tenant-b.com", "role": "viewer"}
    ).json()["data"]["id"]
    member_b = b.get(f"/organizations/{org_b}/members").json()["data"][0]["id"]
    return {"a": a, "b": b, "org_a": org_a, "org_b": org_b, "inv_b": inv_b, "member_b": member_b}


def _org_routes(app):
    for path, methods in app.openapi()["paths"].items():
        if "{organization_id}" in path:
            for method in methods:
                yield method, path.removeprefix("/api/v1")


def _call(client, method, path, body):
    if method == "get":
        return client.get(path)
    if method == "delete":
        return client.delete(path)
    return getattr(client, method)(path, body)


def test_every_org_route_returns_404_for_non_members(app, tenants):
    routes = list(_org_routes(app))
    assert len(routes) >= 9  # all Phase 1A organization-scoped operations
    for method, template in routes:
        path = (
            template.replace("{organization_id}", tenants["org_b"])
            .replace("{member_id}", tenants["member_b"])
            .replace("{invitation_id}", tenants["inv_b"])
        )
        assert not re.search(r"\{\w+\}", path), f"unhandled path parameter in {template}"
        response = _call(tenants["a"], method, path, BODIES.get((method, template), {}))
        assert response.status_code == 404, f"{method.upper()} {template} -> {response.status_code}"
        assert response.json()["error"]["code"] == "NOT_FOUND"


def test_foreign_child_ids_under_own_org_return_404(tenants):
    a, org_a = tenants["a"], tenants["org_a"]
    assert (
        a.patch(
            f"/organizations/{org_a}/members/{tenants['member_b']}", {"role": "viewer"}
        ).status_code
        == 404
    )
    assert a.delete(f"/organizations/{org_a}/members/{tenants['member_b']}").status_code == 404
    assert a.delete(f"/organizations/{org_a}/invitations/{tenants['inv_b']}").status_code == 404


def test_tenant_b_data_unchanged_and_invisible(tenants):
    b, org_b, a = tenants["b"], tenants["org_b"], tenants["a"]
    assert b.get(f"/organizations/{org_b}").json()["data"]["name"] == "Tenant B"
    assert [o["name"] for o in a.get("/organizations").json()["data"]] == ["Tenant A"]
    a_logs = a.get(f"/organizations/{tenants['org_a']}/audit-logs").json()["data"]
    assert all(e["resource_id"] != org_b for e in a_logs)
    assert all("tenant-b" not in str(e) for e in a_logs)


def test_invitation_token_cannot_be_redirected_to_other_tenant(tenants, make_client):
    # A token for tenant B can only ever join tenant B, whatever the caller sends.
    token = last_email("pending@tenant-b.com", "invited").text.split("#token=")[1].split()[0]
    joiner = make_client()
    joiner.signup("pending@tenant-b.com")
    response = joiner.post(
        "/invitations/accept", {"token": token, "organization_id": tenants["org_a"]}
    )
    assert response.status_code == 422  # unknown fields are rejected outright
    assert (
        joiner.post("/invitations/accept", {"token": token}).json()["data"]["id"]
        == tenants["org_b"]
    )
    assert joiner.get(f"/organizations/{tenants['org_a']}").status_code == 404
