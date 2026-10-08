"""Audit trail: material actions are recorded, filtered, paginated and access-controlled."""

from __future__ import annotations


def test_audit_trail_records_material_actions(make_client):
    owner, member = make_client(), make_client()
    owner.signup("aud@example.com")
    oid = owner.create_org("Audited")["id"]
    member.signup("m@example.com")
    member_id = owner.invite_and_join(oid, member, "m@example.com", "viewer")
    owner.patch(f"/organizations/{oid}/members/{member_id}", {"role": "analyst"})
    owner.patch(f"/organizations/{oid}", {"name": "Audited Two"})

    response = owner.get(f"/organizations/{oid}/audit-logs")
    assert response.status_code == 200
    body = response.json()
    actions = [e["action"] for e in body["data"]]
    for expected in (
        "organization.created",
        "membership.created",
        "invitation.created",
        "invitation.accepted",
        "membership.updated",
        "organization.updated",
    ):
        assert expected in actions
    assert body["meta"]["total"] == len(actions)
    update = next(e for e in body["data"] if e["action"] == "membership.updated")
    assert update["before"] == {"role": "viewer", "status": "active"}
    assert update["after"] == {"role": "analyst", "status": "active"}
    assert update["correlation_id"]

    filtered = owner.get(
        f"/organizations/{oid}/audit-logs", params={"action": "organization.updated"}
    ).json()
    assert filtered["meta"]["total"] == 1
    paged = owner.get(f"/organizations/{oid}/audit-logs", params={"page": 2, "page_size": 2}).json()
    assert paged["meta"]["page"] == 2
    assert len(paged["data"]) == 2
    assert (
        owner.get(f"/organizations/{oid}/audit-logs", params={"page_size": 101}).status_code == 422
    )
    by_type = owner.get(
        f"/organizations/{oid}/audit-logs",
        params={"resource_type": "invitation", "result": "success"},
    ).json()
    assert {e["resource_type"] for e in by_type["data"]} == {"invitation"}
    me_id = owner.get("/auth/me").json()["data"]["id"]
    by_actor = owner.get(
        f"/organizations/{oid}/audit-logs",
        params={
            "actor_user_id": me_id,
            "created_from": "2000-01-01T00:00:00Z",
            "created_to": "2999-01-01T00:00:00Z",
        },
    ).json()
    assert by_actor["meta"]["total"] >= 4


def test_audit_payloads_never_contain_secrets(make_client, admin_engine):
    from sqlalchemy import text

    owner = make_client()
    owner.signup("sec@example.com")
    oid = owner.create_org()["id"]
    owner.post(f"/organizations/{oid}/invitations", {"email": "z@example.com", "role": "viewer"})
    with admin_engine.connect() as conn:
        dump = " ".join(
            str(r)
            for r in conn.execute(
                text("SELECT before_json, after_json, metadata FROM audit_logs")
            ).all()
        )
        events = " ".join(
            str(r)
            for r in conn.execute(text("SELECT metadata, ip_hash FROM security_events")).all()
        )
    assert "token" not in dump.lower()
    assert "password" not in dump.lower()
    assert "testclient" not in events  # raw IPs are never stored
