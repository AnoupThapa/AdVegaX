"""The Admin portal (Phase 16, tasks 16-03 … 16-05): administrators only, two-step sign-in,
encrypted keys never shown again, switches, organizations and people, health, audit."""

from __future__ import annotations

import uuid
from datetime import timedelta

from app.domains.platform import store, totp
from app.domains.platform.make_admin import make
from sqlalchemy import text

from tests.api.test_actions_api import rows

ADMIN = "operator@example.com"


def code_for(secret, clock):
    return totp.code_at(secret, int(clock.now().timestamp()) // totp.STEP)


def signed_in_admin(make_client, clock):
    c = make_client()
    c.signup(ADMIN)
    assert make(ADMIN) is True
    secret = c.post("/admin/two-step/setup").json()["data"]["secret"]
    enabled = c.post("/admin/two-step/enable", {"code": code_for(secret, clock)})
    assert enabled.status_code == 200, enabled.text
    c.secret = secret
    return c


def test_customers_never_reach_the_admin_portal(make_client):
    c = make_client()
    c.signup("customer@example.com")
    assert c.get("/admin/me").json()["data"] == {
        "is_admin": False,
        "totp_enabled": False,
        "verified": False,
    }
    for path in ("/admin/settings", "/admin/organizations", "/admin/users", "/admin/health"):
        refused = c.get(path)
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "ADMIN_REQUIRED"
    assert c.post("/admin/two-step/setup").status_code == 403
    org = c.create_org("Customer Co")["id"]
    status = c.put(f"/admin/organizations/{org}/status", {"status": "suspended"})
    assert status.status_code == 403 and status.json()["error"]["code"] == "ADMIN_REQUIRED"
    assert make("nobody@example.com") is False


def test_two_step_sign_in(make_client, clock):
    c = make_client()
    c.signup(ADMIN)
    make(ADMIN)
    assert c.get("/admin/me").json()["data"]["is_admin"] is True
    assert c.get("/admin/settings").json()["error"]["code"] == "ADMIN_CODE_REQUIRED"
    setup = c.post("/admin/two-step/setup").json()["data"]
    assert setup["uri"].startswith("otpauth://totp/AdVegaX%20Admin:")
    wrong = c.post("/admin/two-step/enable", {"code": "000000"})
    assert wrong.status_code == 422
    assert c.post("/admin/two-step/enable", {"code": code_for(setup["secret"], clock)}).json()[
        "data"
    ] == {"is_admin": True, "totp_enabled": True, "verified": True}
    assert c.post("/admin/two-step/setup").status_code == 409
    assert c.get("/admin/settings").status_code == 200
    # A new sign-in needs the code again.
    assert c.login(ADMIN).status_code == 200
    assert c.get("/admin/settings").json()["error"]["code"] == "ADMIN_CODE_REQUIRED"
    assert c.post("/admin/two-step/verify", {"code": "123456"}).status_code == 422
    # The code just used to switch two-step on cannot be used again (QA-013) …
    reused = c.post("/admin/two-step/verify", {"code": code_for(setup["secret"], clock)})
    assert reused.status_code == 422
    # … the next one can.
    clock.advance(timedelta(seconds=totp.STEP * 3))
    ok = c.post("/admin/two-step/verify", {"code": code_for(setup["secret"], clock)})
    assert ok.json()["data"]["verified"] is True
    assert c.get("/admin/settings").status_code == 200


def test_two_step_codes_cannot_be_guessed_or_reused(make_client, clock, admin_engine):
    """QA-003 / QA-013: attempts are limited per person and failures are audited."""
    c = signed_in_admin(make_client, clock)
    assert c.login(ADMIN).status_code == 200
    for _ in range(4):  # the enable call above was the first of five attempts
        assert c.post("/admin/two-step/verify", {"code": "000000"}).status_code == 422
    limited = c.post("/admin/two-step/verify", {"code": "000000"})
    assert limited.status_code == 429
    # Even the right code is refused while limited …
    clock.advance(timedelta(seconds=totp.STEP * 3))
    assert c.post("/admin/two-step/verify", {"code": code_for(c.secret, clock)}).status_code == 429
    # … and accepted once the window has passed.
    clock.advance(timedelta(minutes=15))
    ok = c.post("/admin/two-step/verify", {"code": code_for(c.secret, clock)})
    assert ok.status_code == 200, ok.text
    with admin_engine.connect() as conn:
        failed = conn.execute(
            text("SELECT count(*) FROM audit_logs WHERE action = 'platform.code_failed'")
        ).scalar_one()
    assert failed == 4


def test_keys_are_sealed_and_never_shown(make_client, clock, settings, admin_engine):
    c = signed_in_admin(make_client, clock)
    listed = {s["name"]: s for s in c.get("/admin/settings").json()["data"]}
    assert listed["ANTHROPIC_API_KEY"]["set"] is False
    saved = c.put("/admin/settings/ANTHROPIC_API_KEY", {"value": "sk-ant-demo-secret-9876"})
    assert saved.status_code == 200, saved.text
    assert "sk-ant-demo-secret" not in saved.text
    key = next(s for s in saved.json()["data"] if s["name"] == "ANTHROPIC_API_KEY")
    assert (key["set"], key["hint"], key["source"]) == (True, "••••9876", "portal")
    (row,) = rows(admin_engine, "SELECT ciphertext FROM platform_settings")
    assert b"sk-ant-demo-secret" not in bytes(row["ciphertext"])
    assert c.put("/admin/settings/AGENCY_ENABLED", {"value": "true"}).status_code == 200
    assert c.put("/admin/settings/AGENCY_ENABLED", {"value": "maybe"}).status_code == 422
    bad = c.put("/admin/settings/META_APP_ID", {"value": "not-a-number"})
    assert bad.json()["error"]["details"] == [{"field": "value", "reason": "not_accepted"}]
    assert c.put("/admin/settings/SECRET_KEY", {"value": "x" * 40}).status_code == 404

    applied = store.apply(settings)  # what AdVegaX uses the next time it starts
    assert applied.ANTHROPIC_API_KEY.get_secret_value() == "sk-ant-demo-secret-9876"
    assert applied.AGENCY_ENABLED is True
    assert c.get("/admin/health").json()["data"]["restart_needed"] is True

    audit = rows(
        admin_engine,
        "SELECT action, after_json FROM audit_logs WHERE action LIKE 'platform.setting%'",
    )
    assert {
        "action": "platform.setting_saved",
        "after_json": {"setting": "ANTHROPIC_API_KEY"},
    } in audit
    cleared = c.delete("/admin/settings/ANTHROPIC_API_KEY").json()["data"]
    assert next(s for s in cleared if s["name"] == "ANTHROPIC_API_KEY")["source"] != "portal"


def test_organizations_people_and_health(make_client, clock):
    c = signed_in_admin(make_client, clock)
    owner = make_client()
    owner.signup("shop@example.com")
    org = owner.create_org("Shop Co")["id"]
    listed = c.get("/admin/organizations").json()["data"]
    assert {"id": org, "name": "Shop Co", "status": "active"} in listed
    suspended = c.put(f"/admin/organizations/{org}/status", {"status": "suspended"})
    assert suspended.json()["data"]["status"] == "suspended"
    assert owner.get(f"/organizations/{org}").status_code == 404
    c.put(f"/admin/organizations/{org}/status", {"status": "active"})
    assert owner.get(f"/organizations/{org}").status_code == 200
    missing = c.put(f"/admin/organizations/{uuid.uuid4()}/status", {"status": "active"})
    assert missing.status_code == 404
    people = {u["email"]: u for u in c.get("/admin/users").json()["data"]}
    assert people[ADMIN]["is_admin"] is True and people["shop@example.com"]["is_admin"] is False
    health = c.get("/admin/health").json()["data"]
    assert health["database"] is True and health["redis"] is True
    assert "AGENCY_ENABLED" in health["switches"]
    assert health["organizations_total"] >= 1 and health["organizations_active"] >= 1
    assert health["people_total"] >= 2 and health["administrators"] == 1


def test_admin_lists_are_paged_and_searched_in_the_database(make_client, clock):
    """QA-011: no silent cap; search, filter, sort and pages come from the server."""
    c = signed_in_admin(make_client, clock)
    owner = make_client()
    owner.signup("paging@example.com")
    for name in ("Alpha 50% Off", "Beta Co", "Gamma Co"):
        owner.create_org(name)
    first = c.get("/admin/organizations", params={"page_size": 2}).json()
    assert len(first["data"]) == 2 and first["meta"]["total"] >= 3
    second = c.get("/admin/organizations", params={"page_size": 2, "page": 2}).json()
    assert {o["name"] for o in first["data"]}.isdisjoint({o["name"] for o in second["data"]})
    found = c.get("/admin/organizations", params={"q": "50%"}).json()
    assert [o["name"] for o in found["data"]] == ["Alpha 50% Off"]
    assert c.get("/admin/organizations", params={"q": "_"}).json()["meta"]["total"] == 0
    beta = c.get("/admin/organizations", params={"q": "beta"}).json()["data"][0]
    c.put(f"/admin/organizations/{beta['id']}/status", {"status": "suspended"})
    suspended = c.get("/admin/organizations", params={"status": "suspended"}).json()
    assert [o["name"] for o in suspended["data"]] == ["Beta Co"]
    assert c.get("/admin/organizations", params={"status": "gone"}).status_code == 422
    by_email = c.get("/admin/users", params={"sort": "email"}).json()["data"]
    assert [u["email"] for u in by_email] == sorted(u["email"] for u in by_email)
    paging = c.get("/admin/users", params={"q": "PAGING"}).json()
    assert [u["email"] for u in paging["data"]] == ["paging@example.com"]
    assert c.get("/admin/users", params={"page_size": 500}).status_code == 422


def test_totp_codes():
    secret = "JBSWY3DPEHPK3PXP"
    assert totp.code_at(secret, 1) == totp.code_at(secret, 1)
    assert len(totp.code_at(secret, 52_000_000)) == 6
    from datetime import UTC, datetime

    now = datetime(2026, 10, 28, tzinfo=UTC)
    good = totp.code_at(secret, int(now.timestamp()) // 30)
    assert totp.verify(secret, good, now)
    assert totp.verify(secret, f" {good[:3]} {good[3:]} ", now)
    assert not totp.verify(secret, "abcdef", now)
    assert not totp.verify(secret, "12345", now)
    assert totp.match(secret, good, now) == int(now.timestamp()) // 30
    assert totp.match(secret, "abcdef", now) is None
