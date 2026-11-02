"""Agency mode (Phase 14, tasks 14-01 … 14-04, PLAN §4 and §5).

An agency organization ("Growth Agency": an owner, a manager and an analyst) and two clients
("Eve Zone", "Mediflex"), each with its own owner. Covers the switch, the code, the grant
lifecycle (offer, accept, end — by either side), the effective role (the lower of the two),
what never passes through an agency (members, billing, settings, autopilot, granting), audit
"via agency" in the client's log, emails, the clients list (each client on its own) and
isolation between agency and clients and between clients.
"""

from __future__ import annotations

import uuid

import pytest

from tests.api.test_actions_api import rows
from tests.helpers import connected, last_email


@pytest.fixture
def world(runtime, make_client):
    runtime.settings = runtime.settings.model_copy(update={"AGENCY_ENABLED": True})
    w = type("World", (), {})()
    w.boss = make_client()
    w.boss.signup("boss@agency.example.com", name="Agency Boss")
    w.agency = w.boss.create_org("Growth Agency")["id"]
    w.manager, w.analyst = make_client(), make_client()
    w.manager.signup("manager@agency.example.com")
    w.analyst.signup("analyst@agency.example.com")
    w.boss.invite_and_join(w.agency, w.manager, "manager@agency.example.com", "manager")
    w.boss.invite_and_join(w.agency, w.analyst, "analyst@agency.example.com", "analyst")
    w.eve = make_client()
    w.eve.signup("owner@evezone.example.com")
    w.client = w.eve.create_org("Eve Zone")["id"]
    w.medi = make_client()
    w.medi.signup("owner@mediflex.example.com")
    w.other = w.medi.create_org("Mediflex")["id"]
    w.code = w.boss.post(f"/organizations/{w.agency}/agency/code").json()["data"]["code"]
    return w


def offer(c, org, code, role="manager"):
    return c.post(f"/organizations/{org}/agency/grants", {"code": code, "role": role})


def connect(w, role="manager"):
    made = offer(w.eve, w.client, w.code, role)
    assert made.status_code == 201, made.text
    grant = made.json()["data"]["id"]
    accepted = w.boss.post(f"/organizations/{w.agency}/agency/grants/{grant}/accept")
    assert accepted.status_code == 200, accepted.text
    return grant


def code(response):
    return response.json()["error"]["code"]


def test_switched_off_by_default(runtime, make_client):
    c = make_client()
    c.signup("solo@example.com")
    org = c.create_org("Solo")["id"]
    data = c.get(f"/organizations/{org}/agency").json()["data"]
    assert data == {
        "enabled": False,
        "code": None,
        "can_grant": False,
        "can_manage": False,
        "agencies": [],
        "clients": [],
    }
    assert c.post(f"/organizations/{org}/agency/code").status_code == 409
    assert offer(c, org, "ABCDEFGHJK").status_code == 409


def test_offer_accept_and_work_in_the_client(world, admin_engine):
    w = world
    made = offer(w.eve, w.client, w.code.lower())  # codes are not case-sensitive
    assert made.status_code == 201, made.text
    grant = made.json()["data"]
    assert (grant["status"], grant["role"], grant["agency_name"]) == (
        "pending",
        "manager",
        "Growth Agency",
    )
    assert "Eve Zone gave Growth Agency access" in last_email("boss@agency.example.com").subject
    assert w.manager.get(f"/organizations/{w.client}").status_code == 404  # not yet

    seen = w.boss.get(f"/organizations/{w.agency}/agency").json()["data"]
    assert seen["code"] == w.code and seen["can_manage"] is True
    assert [g["client_name"] for g in seen["clients"]] == ["Eve Zone"]
    accepted = w.boss.post(f"/organizations/{w.agency}/agency/grants/{grant['id']}/accept")
    assert accepted.json()["data"]["status"] == "active"
    assert "now has access" in last_email("owner@evezone.example.com").subject

    org = w.manager.get(f"/organizations/{w.client}").json()["data"]
    assert (org["role"], org["via_agency"]) == ("manager", "Growth Agency")
    listed = w.manager.get("/organizations").json()["data"]
    assert {(o["name"], o["via_agency"]) for o in listed} == {
        ("Growth Agency", None),
        ("Eve Zone", "Growth Agency"),
    }
    # The lower of the two roles: an agency analyst stays an analyst; the agency's owner is
    # capped at the granted role.
    assert w.analyst.get(f"/organizations/{w.client}").json()["data"]["role"] == "analyst"
    assert w.boss.get(f"/organizations/{w.client}").json()["data"]["role"] == "manager"

    # A delegated action is in the client's audit log, "via" the agency.
    conn = connected(w.manager, w.client)
    found = w.manager.get(f"/organizations/{w.client}/connections/{conn}/resources")
    rid = found.json()["data"][0]["id"]
    assert w.manager.post(f"/organizations/{w.client}/resources/{rid}/link").status_code == 201
    (linked,) = rows(
        admin_engine,
        "SELECT organization_id, metadata AS metadata_json FROM audit_logs "
        "WHERE action = 'resource.linked'",
    )
    assert linked["organization_id"] == uuid.UUID(w.client)
    assert linked["metadata_json"]["via_agency_id"] == w.agency
    own = w.eve.get(f"/organizations/{w.client}/agency").json()["data"]
    assert [(g["agency_name"], g["status"]) for g in own["agencies"]] == [
        ("Growth Agency", "active")
    ]


def test_what_never_passes_through_an_agency(world):
    w = world
    connect(w)
    base = f"/organizations/{w.client}"
    for path in ("/members", "/invitations", "/billing", "/audit-logs"):
        assert w.boss.get(f"{base}{path}").status_code == 403, path
    assert w.boss.patch(base, {"name": "Taken"}).status_code == 403
    invite = w.boss.post(f"{base}/invitations", {"email": "x@example.com", "role": "viewer"})
    assert invite.status_code == 403
    assert w.boss.post(f"{base}/autopilot/enable", {"confirm": "Eve Zone"}).status_code == 403
    assert offer(w.boss, w.client, w.code).status_code == 403
    assert w.boss.get(f"{base}/agency").json()["data"]["agencies"] == []  # not the client's list
    assert w.boss.get(f"{base}/clients").status_code == 404


def test_either_side_ends_access_at_once(world):
    w = world
    grant = connect(w)
    assert w.manager.get(f"/organizations/{w.client}").status_code == 200
    ended = w.eve.post(f"/organizations/{w.client}/agency/grants/{grant}/revoke")
    assert ended.json()["data"]["status"] == "revoked"
    assert w.manager.get(f"/organizations/{w.client}").status_code == 404
    assert "Agency access ended" in last_email("boss@agency.example.com").subject
    again = w.eve.post(f"/organizations/{w.client}/agency/grants/{grant}/revoke")
    assert again.status_code == 409
    # Offered again, accepted, then ended by the agency.
    second = connect(w)
    assert second != grant
    assert (
        w.boss.post(f"/organizations/{w.agency}/agency/grants/{second}/revoke").status_code == 200
    )
    assert w.manager.get(f"/organizations/{w.client}").status_code == 404
    history = w.eve.get(f"/organizations/{w.client}/agency").json()["data"]["agencies"]
    assert [g["status"] for g in history] == ["revoked", "revoked"]


def test_refusals(world):
    w = world
    unknown = offer(w.eve, w.client, "ZZZZZZZZZZ")
    assert unknown.status_code == 422
    assert unknown.json()["error"]["details"] == [
        {"field": "code", "reason": "unknown_agency_code"}
    ]
    own_code = w.eve.post(f"/organizations/{w.client}/agency/code").json()["data"]["code"]
    assert offer(w.eve, w.client, own_code).json()["error"]["details"][0]["reason"] == "own_code"
    assert offer(w.eve, w.client, w.code, role="admin").status_code == 422  # never above manager
    grant = offer(w.eve, w.client, w.code).json()["data"]["id"]
    assert code(offer(w.eve, w.client, w.code)) == "CONFLICT"
    # Only the agency accepts; only once; staff below admin cannot.
    assert w.eve.post(f"/organizations/{w.client}/agency/grants/{grant}/accept").status_code == 404
    assert (
        w.manager.post(f"/organizations/{w.agency}/agency/grants/{grant}/accept").status_code == 403
    )
    assert w.boss.post(f"/organizations/{w.agency}/agency/grants/{grant}/accept").status_code == 200
    assert w.boss.post(f"/organizations/{w.agency}/agency/grants/{grant}/accept").status_code == 409
    # Only the client's owner offers access.
    w.eve.invite_and_join(w.client, w.medi, "owner@mediflex.example.com", "admin")
    assert offer(w.medi, w.client, w.code).status_code == 403
    # Another organization never sees a grant.
    assert w.medi.post(f"/organizations/{w.other}/agency/grants/{grant}/revoke").status_code == 404
    # A new code: the old one stops working; the grant already made stays.
    w.boss.post(f"/organizations/{w.agency}/agency/code")
    assert offer(w.medi, w.other, w.code).status_code == 422
    assert w.manager.get(f"/organizations/{w.client}").status_code == 200


def test_clients_stay_apart(world):
    w = world
    connect(w)
    assert w.manager.get(f"/organizations/{w.other}").status_code == 404  # no grant
    conn = connected(w.manager, w.client)
    made = offer(w.medi, w.other, w.code, role="viewer").json()["data"]["id"]
    w.boss.post(f"/organizations/{w.agency}/agency/grants/{made}/accept")
    assert w.manager.get(f"/organizations/{w.other}").json()["data"]["role"] == "viewer"
    others = w.manager.get(f"/organizations/{w.other}/connections").json()["data"]
    assert others == []
    assert w.manager.get(f"/organizations/{w.other}/connections/{conn}").status_code == 404
    assert w.medi.get(f"/organizations/{w.client}").status_code == 404
    # The agency's own data is not the clients' either.
    assert w.eve.get(f"/organizations/{w.agency}").status_code == 404

    listed = w.manager.get(f"/organizations/{w.agency}/clients").json()["data"]
    assert [(c["name"], c["role"], c["currency"]) for c in listed] == [
        ("Eve Zone", "manager", "AUD"),
        ("Mediflex", "viewer", "AUD"),
    ]
    first = listed[0]
    assert first["billing_status"] == "off" and first["open_recommendations"] == 0
    assert first["connections_needing_attention"] == 0
    assert first["ad_spend"]["availability"]  # computed for this client alone


def test_switching_off_ignores_every_grant(world, runtime):
    w = world
    connect(w)
    runtime.settings = runtime.settings.model_copy(update={"AGENCY_ENABLED": False})
    assert w.manager.get(f"/organizations/{w.client}").status_code == 404
    names = {o["name"] for o in w.manager.get("/organizations").json()["data"]}
    assert names == {"Growth Agency"}
