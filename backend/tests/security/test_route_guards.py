"""Authentication, CSRF and input-validation guards for every API route (PHASE_01B_PLAN §14).

Generated from the OpenAPI schema, so routes added in later phases are covered automatically.
Tenant isolation (404 for non-members) is covered separately in ``test_tenant_isolation.py``.
"""

from __future__ import annotations

import re
import uuid

import pytest

from tests.helpers import ORIGIN, connected

UNSAFE = {"post", "put", "patch", "delete"}

# Routes that are intentionally reachable without a session. Everything else must return 401.
PUBLIC = {
    ("get", "/health/live"),
    ("get", "/health/ready"),
    ("get", "/auth/csrf"),
    ("post", "/auth/register"),
    ("post", "/auth/verify-email"),
    ("post", "/auth/login"),
    ("post", "/auth/logout"),
    ("post", "/auth/forgot-password"),
    ("post", "/auth/reset-password"),
}

PARAM = re.compile(r"\{(\w+)\}")


def _routes(app):
    for path, methods in app.openapi()["paths"].items():
        for method in methods:
            yield method, path.removeprefix("/api/v1")


def _fill(path: str, values: dict[str, str]) -> str:
    return PARAM.sub(lambda m: values.get(m.group(1), str(uuid.uuid4())), path)


def _request(client, method, path, *, headers):
    kwargs = {"headers": headers}
    if method == "post" and path.endswith("/creative-assets"):
        kwargs["files"] = {"file": ("a.png", b"\x89PNG", "image/png")}  # the upload route (9-05)
    elif method in UNSAFE and method != "delete":
        kwargs["json"] = {}
    return client.http.request(method.upper(), f"/api/v1{path}", **kwargs)


def test_public_allowlist_matches_real_routes(app):
    assert PUBLIC <= set(_routes(app)), "PUBLIC lists a route that no longer exists"


def test_every_protected_route_requires_a_session(app, client):
    """Signed-out callers (with a valid anonymous CSRF token) get 401 everywhere else."""
    token = client.refresh_csrf()
    checked = 0
    for method, path in _routes(app):
        if (method, path) in PUBLIC:
            continue
        headers = {"Origin": ORIGIN, "X-CSRF-Token": token} if method in UNSAFE else {}
        response = _request(client, method, _fill(path, {"provider": "fake"}), headers=headers)
        assert response.status_code == 401, (method, path, response.status_code)
        assert response.json()["error"]["code"] == "UNAUTHENTICATED", (method, path)
        checked += 1
    assert checked >= 25


@pytest.fixture
def signed_in(make_client):
    c = make_client()
    c.signup("guards@example.com")
    org = c.create_org("Guard Co")["id"]
    conn = connected(c, org)
    resource = c.get(f"/organizations/{org}/connections/{conn}/resources").json()["data"][0]["id"]
    values = {
        "organization_id": org,
        "connection_id": conn,
        "resource_id": resource,
        "provider": "fake",
    }
    return c, values


def test_every_unsafe_route_requires_the_csrf_token(app, signed_in):
    """A signed-in browser request without the CSRF header is refused before any handler runs."""
    client, values = signed_in
    before = client.get(f"/organizations/{values['organization_id']}/connections").json()["data"]
    checked = 0
    for method, path in _routes(app):
        if method not in UNSAFE:
            continue
        for headers in ({"Origin": ORIGIN}, {"Origin": ORIGIN, "X-CSRF-Token": "forged.value"}):
            response = _request(client, method, _fill(path, values), headers=headers)
            assert response.status_code == 403, (method, path, response.status_code)
            assert response.json()["error"]["code"] == "CSRF_FAILED", (method, path)
        checked += 1
    assert checked >= 20
    # Nothing changed: the connection is still active and the session still works.
    after = client.get(f"/organizations/{values['organization_id']}/connections").json()["data"]
    assert after == before
    assert after[0]["status"] == "active"


def test_malformed_identifiers_are_rejected(app, signed_in):
    """Every route with an ID in its path validates it (422) instead of reaching the database."""
    client, values = signed_in
    checked = 0
    for method, path in _routes(app):
        names = [n for n in PARAM.findall(path) if n.endswith("_id")]
        if not names:
            continue
        for name in names:
            bad = dict(values, **{name: "not-a-uuid"})
            target = _fill(path, bad)
            if method == "get":
                response = client.get(target)
            elif method == "delete":
                response = client.delete(target)
            else:
                response = getattr(client, method)(target, {})
            assert response.status_code == 422, (method, path, name, response.status_code)
            body = response.json()["error"]
            assert body["code"] == "VALIDATION_ERROR", (method, path, name)
            assert "not-a-uuid" not in response.text, "submitted values must not be echoed"
            checked += 1
    assert checked >= 15


def test_unknown_provider_is_rejected_on_start(signed_in):
    client, values = signed_in
    for code in ("shopify", "FAKE", "fake%2F..", "x" * 200):
        response = client.post(
            f"/organizations/{values['organization_id']}/connections/{code}/start"
        )
        assert response.status_code in (404, 422), code
        assert response.json()["error"]["code"] in (
            "UNKNOWN_PROVIDER",
            "VALIDATION_ERROR",
            "NOT_FOUND",
        )
