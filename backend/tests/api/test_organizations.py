"""Organizations, members, roles and the last-owner invariant."""

from __future__ import annotations

from tests.helpers import new_uuid


def test_unverified_user_cannot_create_organization(client):
    client.signup("u@example.com", verified=False)
    response = client.post(
        "/organizations", {"name": "X", "default_currency": "AUD", "default_timezone": "UTC"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"


def test_create_list_get_update_organization(client):
    client.signup("owner@example.com")
    org = client.create_org("Eve Zone Wholesale")
    assert org["role"] == "owner"
    assert org["slug"] == "eve-zone-wholesale"
    assert org["default_currency"] == "AUD"
    listed = client.get("/organizations").json()["data"]
    assert [o["id"] for o in listed] == [org["id"]]
    assert client.get(f"/organizations/{org['id']}").json()["data"]["name"] == "Eve Zone Wholesale"
    updated = client.patch(
        f"/organizations/{org['id']}", {"name": "Eve Zone", "default_currency": "usd"}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["default_currency"] == "USD"
    me = client.get("/auth/me").json()["data"]
    assert me["memberships"][0]["role"] == "owner"


def test_slug_rules(client):
    client.signup("slug@example.com")
    first = client.create_org("Same Name")
    second = client.create_org("Same Name")
    assert first["slug"] == "same-name"
    assert second["slug"].startswith("same-name-")
    taken = client.post(
        "/organizations",
        {
            "name": "Other",
            "slug": "same-name",
            "default_currency": "AUD",
            "default_timezone": "UTC",
        },
    )
    assert taken.status_code == 409
    assert taken.json()["error"]["code"] == "SLUG_TAKEN"
    short = client.create_org("!")
    assert short["slug"].startswith("org")


def test_organization_validation(client):
    client.signup("val@example.com")
    for body in (
        {"name": "A", "default_currency": "AU", "default_timezone": "UTC"},
        {"name": "A", "default_currency": "A1D", "default_timezone": "UTC"},
        {"name": "A", "default_currency": "AUD", "default_timezone": "Mars/Base"},
        {"name": "A", "default_currency": "AUD", "default_timezone": "UTC", "slug": "Bad Slug"},
        {"name": "", "default_currency": "AUD", "default_timezone": "UTC"},
        {"name": "A", "default_currency": "AUD", "default_timezone": "UTC", "status": "x"},
    ):
        assert client.post("/organizations", body).status_code == 422, body


def test_role_permissions_matrix(make_client):
    owner = make_client()
    owner.signup("o@example.com")
    org = owner.create_org()
    oid = org["id"]
    clients = {}
    for role in ("admin", "manager", "analyst", "viewer"):
        c = make_client()
        c.signup(f"{role}@example.com")
        owner.invite_and_join(oid, c, f"{role}@example.com", role)
        clients[role] = c
    for role, c in clients.items():
        can_manage = role == "admin"
        assert c.get(f"/organizations/{oid}").status_code == 200
        assert c.get(f"/organizations/{oid}/members").status_code == 200
        assert (
            c.patch(f"/organizations/{oid}", {"name": "Renamed"}).status_code == 200
        ) is can_manage
        assert (c.get(f"/organizations/{oid}/invitations").status_code == 200) is can_manage
        assert (c.get(f"/organizations/{oid}/audit-logs").status_code == 200) is can_manage
        forbidden = c.get(f"/organizations/{oid}/audit-logs")
        if not can_manage:
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "FORBIDDEN"


def test_member_role_rules(make_client):
    owner, admin, viewer = make_client(), make_client(), make_client()
    owner.signup("own@example.com")
    oid = owner.create_org()["id"]
    admin.signup("adm@example.com")
    viewer.signup("vw@example.com")
    admin_id = owner.invite_and_join(oid, admin, "adm@example.com", "admin")
    viewer_id = owner.invite_and_join(oid, viewer, "vw@example.com", "viewer")
    owner_id = next(
        m["id"]
        for m in owner.get(f"/organizations/{oid}/members").json()["data"]
        if m["email"] == "own@example.com"
    )

    # Admin may change lower roles but never grant owner or touch an owner.
    assert (
        admin.patch(f"/organizations/{oid}/members/{viewer_id}", {"role": "manager"}).status_code
        == 200
    )
    assert (
        admin.patch(f"/organizations/{oid}/members/{viewer_id}", {"role": "owner"}).status_code
        == 403
    )
    assert (
        admin.patch(f"/organizations/{oid}/members/{owner_id}", {"role": "viewer"}).status_code
        == 403
    )
    assert admin.delete(f"/organizations/{oid}/members/{owner_id}").status_code == 403
    # Viewer cannot manage anyone.
    assert (
        viewer.patch(f"/organizations/{oid}/members/{admin_id}", {"role": "viewer"}).status_code
        == 403
    )
    # Suspend then reactivate.
    assert (
        owner.patch(
            f"/organizations/{oid}/members/{viewer_id}", {"status": "suspended"}
        ).status_code
        == 200
    )
    assert viewer.get(f"/organizations/{oid}").status_code == 404
    assert (
        owner.patch(f"/organizations/{oid}/members/{viewer_id}", {"status": "active"}).status_code
        == 200
    )
    assert viewer.get(f"/organizations/{oid}").status_code == 200
    # Remove.
    assert owner.delete(f"/organizations/{oid}/members/{viewer_id}").status_code == 200
    assert viewer.get(f"/organizations/{oid}").status_code == 404
    assert owner.delete(f"/organizations/{oid}/members/{viewer_id}").status_code == 404
    emails = [m["email"] for m in owner.get(f"/organizations/{oid}/members").json()["data"]]
    assert "vw@example.com" not in emails
    assert (
        owner.patch(f"/organizations/{oid}/members/{new_uuid()}", {"role": "viewer"}).status_code
        == 404
    )


def test_last_owner_cannot_be_removed_or_demoted(make_client):
    owner, second = make_client(), make_client()
    owner.signup("lo@example.com")
    oid = owner.create_org()["id"]
    me = owner.get(f"/organizations/{oid}/members").json()["data"][0]["id"]
    demote = owner.patch(f"/organizations/{oid}/members/{me}", {"role": "admin"})
    assert demote.status_code == 409
    assert demote.json()["error"]["code"] == "LAST_OWNER"
    assert (
        owner.patch(f"/organizations/{oid}/members/{me}", {"status": "suspended"}).status_code
        == 409
    )
    assert owner.delete(f"/organizations/{oid}/members/{me}").status_code == 409
    second.signup("lo2@example.com")
    second_id = owner.invite_and_join(oid, second, "lo2@example.com", "owner")
    assert owner.patch(f"/organizations/{oid}/members/{me}", {"role": "admin"}).status_code == 200
    # now `second` is the only owner
    assert second.delete(f"/organizations/{oid}/members/{second_id}").status_code == 409


def test_concurrent_owner_demotions_keep_one_owner(make_client):
    import threading

    a, b = make_client(), make_client()
    a.signup("ca@example.com")
    oid = a.create_org()["id"]
    b.signup("cb@example.com")
    b_id = a.invite_and_join(oid, b, "cb@example.com", "owner")
    a_id = next(
        m["id"]
        for m in a.get(f"/organizations/{oid}/members").json()["data"]
        if m["email"] == "ca@example.com"
    )
    results: list[int] = []
    barrier = threading.Barrier(2)

    def demote(client, member_id):
        barrier.wait()
        results.append(
            client.patch(f"/organizations/{oid}/members/{member_id}", {"role": "admin"}).status_code
        )

    threads = [
        threading.Thread(target=demote, args=(a, b_id)),
        threading.Thread(target=demote, args=(b, a_id)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    owners = [
        m for m in a.get(f"/organizations/{oid}/members").json()["data"] if m["role"] == "owner"
    ] or [m for m in b.get(f"/organizations/{oid}/members").json()["data"] if m["role"] == "owner"]
    assert len(owners) >= 1
    assert sorted(results) in ([200, 409], [200, 404], [200, 403])


def test_shared_user_sees_both_organizations_only_via_membership(make_client):
    a, b, shared = make_client(), make_client(), make_client()
    a.signup("ta@example.com")
    b.signup("tb@example.com")
    shared.signup("shared@example.com")
    org_a = a.create_org("Tenant A")["id"]
    org_b = b.create_org("Tenant B")["id"]
    a.invite_and_join(org_a, shared, "shared@example.com", "viewer")
    b.invite_and_join(org_b, shared, "shared@example.com", "analyst")
    listed = {o["id"]: o["role"] for o in shared.get("/organizations").json()["data"]}
    assert listed == {org_a: "viewer", org_b: "analyst"}
    assert [o["id"] for o in a.get("/organizations").json()["data"]] == [org_a]
