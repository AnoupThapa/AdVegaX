"""Authentication API: registration, verification, login, sessions, passwords."""

from __future__ import annotations

from datetime import timedelta

from app.domains.notifications.email import memory

from tests.helpers import PASSWORD, last_email, token_from


def test_register_verify_login_me(client, settings):
    assert client.register("Ada@Example.com", name="Ada").status_code == 202
    message = last_email("ada@example.com", "Verify")
    assert message.subject == "Verify your AdVegaX email address"
    assert "http://localhost:3000/verify-email#token=" in message.text
    assert "24 hours" in message.text

    response = client.login("ada@example.com")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["user"]["email_verified"] is False
    assert body["csrf_token"]

    assert client.verify("ada@example.com").status_code == 200
    me = client.get("/auth/me").json()["data"]
    assert me["email"] == "ada@example.com"
    assert me["display_name"] == "Ada"
    assert me["email_verified"] is True
    assert me["memberships"] == []


def test_register_existing_email_is_indistinguishable(client):
    first = client.register("dup@example.com")
    second = client.register("dup@example.com")
    assert first.status_code == second.status_code == 202
    assert first.json()["data"] == second.json()["data"]
    assert last_email("dup@example.com").subject == "You already have an AdVegaX account"


def test_register_rejects_weak_password_and_bad_email(client):
    weak = client.register("weak@example.com", password="short")
    assert weak.status_code == 422
    assert weak.json()["error"]["code"] == "VALIDATION_ERROR"
    same = client.register("same.as.email@example.com", password="same.as.email@example.com")
    assert same.status_code == 422
    bad = client.post("/auth/register", {"email": "not-an-email", "password": PASSWORD})
    assert bad.status_code == 422
    assert "input" not in str(bad.json()["error"]["details"])
    extra = client.post(
        "/auth/register", {"email": "x@example.com", "password": PASSWORD, "role": "owner"}
    )
    assert extra.status_code == 422


def test_verification_token_single_use_and_expiry(client, clock, settings):
    client.register("v@example.com")
    token = token_from(last_email("v@example.com", "Verify"))
    assert client.post("/auth/verify-email", {"token": token}).status_code == 200
    reuse = client.post("/auth/verify-email", {"token": token})
    assert reuse.status_code == 400
    assert reuse.json()["error"]["code"] == "INVALID_TOKEN"

    client.register("late@example.com")
    late = token_from(last_email("late@example.com", "Verify"))
    clock.advance(settings.EMAIL_VERIFICATION_TTL + timedelta(seconds=1))
    assert client.post("/auth/verify-email", {"token": late}).status_code == 400
    assert client.post("/auth/verify-email", {"token": "x" * 43}).status_code == 400


def test_resend_verification_invalidates_previous_token(client):
    client.register("r@example.com")
    first = token_from(last_email("r@example.com", "Verify"))
    client.login("r@example.com")
    assert client.post("/auth/resend-verification").status_code == 202
    second = token_from(last_email("r@example.com", "Verify"))
    assert first != second
    assert client.post("/auth/verify-email", {"token": first}).status_code == 400
    assert client.post("/auth/verify-email", {"token": second}).status_code == 200
    sent_before = len(memory.SENT)
    assert client.post("/auth/resend-verification").status_code == 202  # already verified: no-op
    assert len(memory.SENT) == sent_before


def test_login_failures_are_generic(client):
    client.register("l@example.com")
    wrong = client.login("l@example.com", "wrong password value")
    unknown = client.login("nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"] == unknown.json()["error"]
    assert wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_disabled_user_cannot_login(client, admin_engine):
    from sqlalchemy import text

    client.signup("dis@example.com")
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE users SET status = 'disabled' WHERE email = 'dis@example.com'"))
    assert client.get("/auth/me").status_code == 401
    assert client.login("dis@example.com").status_code == 401


def test_session_cookie_attributes(client, settings):
    client.register("c@example.com")
    response = client.login("c@example.com")
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith(settings.SESSION_COOKIE_NAME + "="))
    lowered = session_cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    assert f"max-age={int(settings.SESSION_ABSOLUTE_TIMEOUT.total_seconds())}" in lowered
    csrf_cookie = next(c for c in cookies if c.startswith(settings.CSRF_COOKIE_NAME + "="))
    assert "httponly" in csrf_cookie.lower()


def test_login_rotates_session(client, settings):
    client.signup("rot@example.com")
    old = client.http.cookies.get(settings.SESSION_COOKIE_NAME)
    assert client.login("rot@example.com").status_code == 200
    new = client.http.cookies.get(settings.SESSION_COOKIE_NAME)
    assert old != new
    sessions = client.get("/auth/sessions").json()["data"]
    assert len(sessions) == 1  # the previous session was revoked on rotation
    assert sessions[0]["current"] is True


def test_logout_and_logout_all(make_client, settings):
    a, b = make_client(), make_client()
    a.signup("multi@example.com")
    b.login("multi@example.com")
    assert len(a.get("/auth/sessions").json()["data"]) == 2
    assert a.post("/auth/logout").status_code == 200
    assert a.get("/auth/me").status_code == 401
    assert b.get("/auth/me").status_code == 200
    a.login("multi@example.com")
    assert a.post("/auth/logout-all").status_code == 200
    assert a.get("/auth/me").status_code == 401
    assert b.get("/auth/me").status_code == 401


def test_revoke_specific_session(make_client):
    a, b = make_client(), make_client()
    a.signup("s@example.com")
    b.login("s@example.com")
    other = next(s for s in a.get("/auth/sessions").json()["data"] if not s["current"])
    assert a.delete(f"/auth/sessions/{other['id']}").status_code == 200
    assert b.get("/auth/me").status_code == 401
    assert a.delete(f"/auth/sessions/{other['id']}").status_code == 404


def test_cannot_revoke_someone_elses_session(make_client):
    a, b = make_client(), make_client()
    a.signup("owner1@example.com")
    b.signup("owner2@example.com")
    b_session = b.get("/auth/sessions").json()["data"][0]["id"]
    assert a.delete(f"/auth/sessions/{b_session}").status_code == 404
    assert b.get("/auth/me").status_code == 200


def test_idle_and_absolute_expiry_use_settings(client, clock, settings):
    client.signup("exp@example.com")
    clock.advance(settings.SESSION_IDLE_TIMEOUT - timedelta(minutes=1))
    assert client.get("/auth/me").status_code == 200  # touched: idle window slides
    clock.advance(settings.SESSION_IDLE_TIMEOUT - timedelta(minutes=1))
    assert client.get("/auth/me").status_code == 200
    clock.advance(settings.SESSION_IDLE_TIMEOUT + timedelta(seconds=1))
    assert client.get("/auth/me").status_code == 401


def test_absolute_timeout_cannot_be_extended(client, clock, settings):
    client.signup("abs@example.com")
    step = settings.SESSION_IDLE_TIMEOUT - timedelta(hours=1)
    elapsed = timedelta(0)
    while elapsed + step < settings.SESSION_ABSOLUTE_TIMEOUT:
        clock.advance(step)
        elapsed += step
        assert client.get("/auth/me").status_code == 200
    clock.advance(settings.SESSION_ABSOLUTE_TIMEOUT - elapsed + timedelta(seconds=1))
    assert client.get("/auth/me").status_code == 401


def test_forgot_and_reset_password_revokes_sessions(make_client, settings):
    a, b = make_client(), make_client()
    a.signup("pw@example.com")
    assert b.post("/auth/forgot-password", {"email": "pw@example.com"}).status_code == 202
    message = last_email("pw@example.com", "Reset")
    assert "30 minutes" in message.text
    token = token_from(message)
    new_password = "a brand new long passphrase"
    response = b.post("/auth/reset-password", {"token": token, "new_password": new_password})
    assert response.status_code == 200
    assert a.get("/auth/me").status_code == 401
    assert b.login("pw@example.com").status_code == 401
    assert b.login("pw@example.com", new_password).status_code == 200
    assert last_email("pw@example.com").subject == "Your AdVegaX password was changed"
    reuse = b.post("/auth/reset-password", {"token": token, "new_password": new_password + "x"})
    assert reuse.status_code == 400


def test_reset_token_expires_and_unknown_email_is_silent(client, clock, settings):
    client.register("exp2@example.com")
    sent = len(memory.SENT)
    assert client.post("/auth/forgot-password", {"email": "ghost@example.com"}).status_code == 202
    assert len(memory.SENT) == sent
    client.post("/auth/forgot-password", {"email": "exp2@example.com"})
    token = token_from(last_email("exp2@example.com", "Reset"))
    clock.advance(settings.PASSWORD_RESET_TTL + timedelta(seconds=1))
    response = client.post(
        "/auth/reset-password", {"token": token, "new_password": "another long passphrase"}
    )
    assert response.status_code == 400


def test_reset_password_verifies_unverified_email(client):
    client.register("unv@example.com")
    client.post("/auth/forgot-password", {"email": "unv@example.com"})
    token = token_from(last_email("unv@example.com", "Reset"))
    client.post("/auth/reset-password", {"token": token, "new_password": "yet another passphrase"})
    client.login("unv@example.com", "yet another passphrase")
    assert client.get("/auth/me").json()["data"]["email_verified"] is True


def test_reset_rejects_weak_password(client):
    client.register("weak2@example.com")
    client.post("/auth/forgot-password", {"email": "weak2@example.com"})
    token = token_from(last_email("weak2@example.com", "Reset"))
    response = client.post("/auth/reset-password", {"token": token, "new_password": "short"})
    assert response.status_code == 422
    # the token was not consumed by the failed attempt
    ok = client.post(
        "/auth/reset-password", {"token": token, "new_password": "long enough passphrase"}
    )
    assert ok.status_code == 200


def test_change_password(make_client, settings):
    a, b = make_client(), make_client()
    a.signup("chg@example.com")
    b.login("chg@example.com")
    old_cookie = a.http.cookies.get(settings.SESSION_COOKIE_NAME)
    bad = a.post(
        "/auth/change-password",
        {"current_password": "wrong one entirely", "new_password": "the new passphrase"},
    )
    assert bad.status_code == 401
    ok = a.post(
        "/auth/change-password",
        {"current_password": PASSWORD, "new_password": "the new passphrase"},
    )
    assert ok.status_code == 200
    assert a.http.cookies.get(settings.SESSION_COOKIE_NAME) != old_cookie
    assert a.get("/auth/me").status_code == 200
    assert b.get("/auth/me").status_code == 401
    assert a.login("chg@example.com", "the new passphrase").status_code == 200


def test_unauthenticated_access(client):
    for path in ("/auth/me", "/auth/sessions", "/organizations"):
        response = client.get(path)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert client.post("/auth/logout").status_code == 401
    assert client.post("/auth/resend-verification").status_code == 401


def test_garbage_session_cookie_is_ignored(client, settings):
    client.http.cookies.set(settings.SESSION_COOKIE_NAME, "x" * 300)
    assert client.get("/auth/me").status_code == 401
    client.http.cookies.set(settings.SESSION_COOKIE_NAME, "not-a-real-session-token-value")
    assert client.get("/auth/me").status_code == 401


def test_login_upgrades_outdated_password_hash(client, admin_engine):
    from argon2 import PasswordHasher
    from sqlalchemy import text

    client.register("old@example.com")
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE user_password_credentials SET password_hash = :h"), {"h": weak})
    assert client.login("old@example.com").status_code == 200
    with admin_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT password_hash FROM user_password_credentials")
        ).scalar_one()
    assert stored != weak and "m=65536" in stored


def test_verification_link_invalid_after_email_change(client, admin_engine):
    from sqlalchemy import text

    client.register("change@example.com")
    token = token_from(last_email("change@example.com", "Verify"))
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE users SET email = 'changed@example.com'"))
    assert client.post("/auth/verify-email", {"token": token}).status_code == 400
