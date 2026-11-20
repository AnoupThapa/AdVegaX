"""Invitations: creation rules, acceptance, expiry, revocation."""

from __future__ import annotations

from datetime import timedelta

from tests.helpers import last_email, new_uuid, token_from


def _setup(make_client):
    owner = make_client()
    owner.signup("boss@example.com", name="Boss")
    oid = owner.create_org("Mediflex")["id"]
    return owner, oid


def test_invitation_email_and_acceptance(make_client):
    owner, oid = _setup(make_client)
    response = owner.post(
        f"/organizations/{oid}/invitations", {"email": "New@Example.com", "role": "manager"}
    )
    assert response.status_code == 201
    inv = response.json()["data"]
    assert inv["email"] == "new@example.com"
    assert inv["status"] == "pending"
    message = last_email("new@example.com", "invited")
    assert "Boss invited you to join Mediflex as manager" in message.text
    assert "7 days" in message.text
    assert "/invitations/accept#token=" in message.text

    invitee = make_client()
    invitee.signup("new@example.com")
    accepted = invitee.post("/invitations/accept", {"token": token_from(message)})
    assert accepted.status_code == 200
    assert accepted.json()["data"]["role"] == "manager"
    invitations = owner.get(f"/organizations/{oid}/invitations").json()["data"]
    assert invitations[0]["status"] == "accepted"
    assert invitee.post("/invitations/accept", {"token": token_from(message)}).status_code == 400


def test_acceptance_requires_verified_matching_email(make_client):
    owner, oid = _setup(make_client)
    owner.post(
        f"/organizations/{oid}/invitations", {"email": "target@example.com", "role": "viewer"}
    )
    token = token_from(last_email("target@example.com", "invited"))

    unverified = make_client()
    unverified.signup("target@example.com", verified=False)
    blocked = unverified.post("/invitations/accept", {"token": token})
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"

    other = make_client()
    other.signup("someone.else@example.com")
    mismatch = other.post("/invitations/accept", {"token": token})
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "INVITATION_EMAIL_MISMATCH"
    assert other.get(f"/organizations/{oid}").status_code == 404

    unverified.verify("target@example.com")
    assert unverified.post("/invitations/accept", {"token": token}).status_code == 200


def test_invitation_role_limits_and_duplicates(make_client):
    owner, oid = _setup(make_client)
    admin = make_client()
    admin.signup("admin@example.com")
    owner.invite_and_join(oid, admin, "admin@example.com", "admin")
    assert (
        admin.post(
            f"/organizations/{oid}/invitations", {"email": "x@example.com", "role": "owner"}
        ).status_code
        == 403
    )
    assert (
        admin.post(
            f"/organizations/{oid}/invitations", {"email": "x@example.com", "role": "admin"}
        ).status_code
        == 201
    )
    dup = owner.post(
        f"/organizations/{oid}/invitations", {"email": "admin@example.com", "role": "viewer"}
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "ALREADY_MEMBER"
    assert (
        owner.post(
            f"/organizations/{oid}/invitations", {"email": "x@example.com", "role": "viewer"}
        ).status_code
        == 201
    )
    statuses = sorted(
        i["status"]
        for i in owner.get(f"/organizations/{oid}/invitations").json()["data"]
        if i["email"] == "x@example.com"
    )
    assert statuses == ["pending", "revoked"]
    assert (
        owner.post(
            f"/organizations/{oid}/invitations", {"email": "bad", "role": "viewer"}
        ).status_code
        == 422
    )
    assert (
        owner.post(
            f"/organizations/{oid}/invitations", {"email": "y@example.com", "role": "superuser"}
        ).status_code
        == 422
    )


def test_reinvite_invalidates_previous_link(make_client):
    owner, oid = _setup(make_client)
    owner.post(f"/organizations/{oid}/invitations", {"email": "re@example.com", "role": "viewer"})
    first = token_from(last_email("re@example.com", "invited"))
    owner.post(f"/organizations/{oid}/invitations", {"email": "re@example.com", "role": "analyst"})
    second = token_from(last_email("re@example.com", "invited"))
    invitee = make_client()
    invitee.signup("re@example.com")
    assert invitee.post("/invitations/accept", {"token": first}).status_code == 400
    assert (
        invitee.post("/invitations/accept", {"token": second}).json()["data"]["role"] == "analyst"
    )


def test_invitation_expiry(make_client, clock, settings):
    owner, oid = _setup(make_client)
    owner.post(f"/organizations/{oid}/invitations", {"email": "late@example.com", "role": "viewer"})
    token = token_from(last_email("late@example.com", "invited"))
    invitee = make_client()
    invitee.signup("late@example.com")
    clock.advance(settings.INVITATION_TTL + timedelta(seconds=1))
    invitee.login("late@example.com")  # the session idled out while time passed
    owner.login("boss@example.com")
    assert invitee.post("/invitations/accept", {"token": token}).status_code == 400
    listed = owner.get(f"/organizations/{oid}/invitations").json()["data"]
    assert listed[0]["status"] == "expired"
    # a new invitation replaces the expired one
    assert (
        owner.post(
            f"/organizations/{oid}/invitations", {"email": "late@example.com", "role": "viewer"}
        ).status_code
        == 201
    )


def test_revoke_invitation(make_client):
    owner, oid = _setup(make_client)
    inv = owner.post(
        f"/organizations/{oid}/invitations", {"email": "rv@example.com", "role": "viewer"}
    ).json()["data"]
    token = token_from(last_email("rv@example.com", "invited"))
    assert owner.delete(f"/organizations/{oid}/invitations/{inv['id']}").status_code == 200
    again = owner.delete(f"/organizations/{oid}/invitations/{inv['id']}")
    assert again.status_code == 409
    assert owner.delete(f"/organizations/{oid}/invitations/{new_uuid()}").status_code == 404
    invitee = make_client()
    invitee.signup("rv@example.com")
    assert invitee.post("/invitations/accept", {"token": token}).status_code == 400


def test_removed_member_can_be_reinvited(make_client):
    owner, oid = _setup(make_client)
    member = make_client()
    member.signup("back@example.com")
    member_id = owner.invite_and_join(oid, member, "back@example.com", "viewer")
    owner.delete(f"/organizations/{oid}/members/{member_id}")
    assert member.get(f"/organizations/{oid}").status_code == 404
    owner.invite_and_join(oid, member, "back@example.com", "analyst")
    assert member.get(f"/organizations/{oid}").json()["data"]["role"] == "analyst"


def test_accepting_when_already_member_is_harmless(make_client):
    owner, oid = _setup(make_client)
    owner.post(
        f"/organizations/{oid}/invitations", {"email": "twice@example.com", "role": "viewer"}
    )
    token = token_from(last_email("twice@example.com", "invited"))
    member = make_client()
    member.signup("twice@example.com")
    member.post("/invitations/accept", {"token": token})
    # Owner invites again while already a member -> ALREADY_MEMBER; acceptance idempotent otherwise.
    assert (
        owner.post(
            f"/organizations/{oid}/invitations", {"email": "twice@example.com", "role": "viewer"}
        ).status_code
        == 409
    )
