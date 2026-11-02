"""CSRF, Origin, CORS, headers, body guards and error hygiene (PHASE_01A_PLAN §14, §16.2)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import ORIGIN, PASSWORD


def _raw_post(client, path, *, headers, json=None):
    return client.http.post(
        f"/api/v1{path}", json=json if json is not None else {}, headers=headers
    )


def test_csrf_required_on_every_unsafe_request(client):
    body = {"email": "c@example.com", "password": PASSWORD}
    no_token = _raw_post(client, "/auth/register", headers={"Origin": ORIGIN}, json=body)
    assert no_token.status_code == 403
    assert no_token.json()["error"]["code"] == "CSRF_FAILED"
    token = client.refresh_csrf()
    wrong = _raw_post(
        client, "/auth/register", headers={"Origin": ORIGIN, "X-CSRF-Token": token + "x"}, json=body
    )
    assert wrong.status_code == 403
    forged = _raw_post(
        client, "/auth/register", headers={"Origin": ORIGIN, "X-CSRF-Token": "abc.def"}, json=body
    )
    assert forged.status_code == 403
    good = _raw_post(
        client, "/auth/register", headers={"Origin": ORIGIN, "X-CSRF-Token": token}, json=body
    )
    assert good.status_code == 202


def test_origin_checks(client):
    token = client.refresh_csrf()
    body = {"email": "o@example.com", "password": PASSWORD}
    for headers in (
        {"Origin": "https://evil.example", "X-CSRF-Token": token},
        {"X-CSRF-Token": token},
        {"Origin": "null", "X-CSRF-Token": token},
        {"Referer": "https://evil.example/page", "X-CSRF-Token": token},
    ):
        assert _raw_post(client, "/auth/register", headers=headers, json=body).status_code == 403
    via_referer = _raw_post(
        client,
        "/auth/register",
        headers={"Referer": f"{ORIGIN}/sign-up", "X-CSRF-Token": token},
        json=body,
    )
    assert via_referer.status_code == 202


def test_csrf_token_bound_to_session(make_client, settings):
    a, b = make_client(), make_client()
    a.signup("bind@example.com")
    b.signup("other-bind@example.com")
    # Anonymous token stops working once a session exists.
    anon = make_client()
    anon_token = anon.refresh_csrf()
    anon.login("bind@example.com")
    stale = _raw_post(anon, "/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": anon_token})
    assert stale.status_code == 403
    # Another user's token (even with matching cookie value copied) fails the binding.
    b.http.cookies.set(settings.CSRF_COOKIE_NAME, a.csrf)
    stolen = _raw_post(b, "/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": a.csrf})
    assert stolen.status_code == 403
    assert a.post("/auth/logout").status_code == 200


def test_cors_allowlist(client):
    allowed = client.http.options(
        "/api/v1/auth/login",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert allowed.headers["access-control-allow-credentials"] == "true"
    denied = client.http.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in denied.headers
    simple = client.http.get("/api/v1/health/live", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


def test_security_headers_and_request_id(client):
    response = client.get("/health/live", headers={"X-Request-ID": "abc12345-req"})
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in response.headers  # only when deployed
    assert response.headers["x-request-id"] == "abc12345-req"
    generated = client.get("/health/live", headers={"X-Request-ID": "bad id!"})
    assert generated.headers["x-request-id"] != "bad id!"
    err = client.get("/auth/me")
    assert err.json()["meta"]["request_id"] == err.headers["x-request-id"]


def test_body_size_and_content_type(client, settings):
    token = client.refresh_csrf()
    headers = {"Origin": ORIGIN, "X-CSRF-Token": token}
    big = client.http.post(
        "/api/v1/auth/register",
        content=b"{" + b" " * settings.MAX_REQUEST_BYTES + b"}",
        headers={**headers, "Content-Type": "application/json"},
    )
    assert big.status_code == 413
    bad_len = client.http.post(
        "/api/v1/auth/register",
        content=b"{}",
        headers={**headers, "Content-Type": "application/json", "Content-Length": "abc"},
    )
    assert bad_len.status_code in (400, 413)
    form = client.http.post(
        "/api/v1/auth/register",
        content=b"email=a",
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert form.status_code == 415


def test_errors_never_leak_internals(client):
    not_found = client.get("/does-not-exist")
    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "NOT_FOUND"
    method = client.http.put("/api/v1/auth/me", headers={"Origin": ORIGIN})
    assert method.status_code in (403, 405)
    invalid = client.post("/auth/login", {"email": "a@example.com"})
    assert invalid.status_code == 422
    text = invalid.text.lower()
    assert "traceback" not in text
    assert "a@example.com" not in text  # inputs are not echoed back


def test_unhandled_exception_returns_generic_500(app, client, monkeypatch):
    from app.domains.identity.service import IdentityService

    def boom(self, principal):
        raise RuntimeError("database password=hunter2 exploded")

    monkeypatch.setattr(IdentityService, "me", boom)
    client.register("boom@example.com")
    with TestClient(app, raise_server_exceptions=False) as raw:
        login = raw.post(
            "/api/v1/auth/login",
            json={"email": "boom@example.com", "password": PASSWORD},
            headers={"Origin": ORIGIN, "X-CSRF-Token": _anon_token(raw)},
        )
    assert login.status_code == 500
    assert login.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "An unexpected error occurred.",
        "details": [],
    }
    assert "hunter2" not in login.text


def _anon_token(raw):
    return raw.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]


def test_readiness(client, runtime, monkeypatch):
    assert client.get("/health/ready").json() == {"status": "ok"}
    import redis

    def down():
        raise redis.ConnectionError("down")

    monkeypatch.setattr(runtime.redis, "ping", down)
    failing = client.get("/health/ready")
    assert failing.status_code == 503
    assert failing.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
