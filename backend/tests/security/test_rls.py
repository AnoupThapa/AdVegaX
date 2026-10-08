"""Database-level isolation as the runtime role (PHASE_01A_PLAN §13, §16.1)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

RLS_TABLES = ("organizations", "memberships", "invitations", "audit_logs")


@pytest.fixture
def seeded(make_client):
    a, b = make_client(), make_client()
    a.signup("rls-a@example.com")
    b.signup("rls-b@example.com")
    org_a = a.create_org("RLS A")["id"]
    org_b = b.create_org("RLS B")["id"]
    a.post(f"/organizations/{org_a}/invitations", {"email": "x@example.com", "role": "viewer"})
    b.post(f"/organizations/{org_b}/invitations", {"email": "y@example.com", "role": "viewer"})
    user_a = a.get("/auth/me").json()["data"]["id"]
    return {"org_a": org_a, "org_b": org_b, "user_a": user_a}


@pytest.fixture
def app_engine(settings):
    engine = create_engine(settings.DATABASE_URL_APP.get_secret_value())
    yield engine
    engine.dispose()


def _ctx(conn, org=None, user=None):
    conn.execute(
        text(
            "SELECT set_config('app.current_org_id', :o, true), "
            "set_config('app.current_user_id', :u, true)"
        ),
        {"o": org or "", "u": user or ""},
    )


def test_no_context_sees_no_tenant_rows(seeded, app_engine):
    with app_engine.begin() as conn:
        for table in RLS_TABLES:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table


def test_context_a_never_sees_b(seeded, app_engine):
    with app_engine.begin() as conn:
        _ctx(conn, org=seeded["org_a"], user=seeded["user_a"])
        for table in ("invitations", "audit_logs", "memberships"):
            orgs = {str(r[0]) for r in conn.execute(text(f"SELECT organization_id FROM {table}"))}
            assert orgs == {seeded["org_a"]}, table
        ids = {str(r[0]) for r in conn.execute(text("SELECT id FROM organizations"))}
        assert ids == {seeded["org_a"]}


def test_user_context_lists_only_own_memberships(seeded, app_engine):
    with app_engine.begin() as conn:
        _ctx(conn, user=seeded["user_a"])
        rows = conn.execute(text("SELECT organization_id FROM memberships")).all()
        assert {str(r[0]) for r in rows} == {seeded["org_a"]}
        assert conn.execute(text("SELECT count(*) FROM invitations")).scalar_one() == 0


def test_cannot_write_into_another_tenant(seeded, app_engine):
    statements = [
        (
            "INSERT INTO invitations (id, organization_id, email, role, status, expires_at) "
            "VALUES (:id, :b, 'p@example.com', 'owner', 'pending', now())"
        ),
        (
            "INSERT INTO memberships (id, organization_id, user_id, role) "
            "VALUES (:id, :b, :u, 'owner')"
        ),
        (
            "INSERT INTO audit_logs "
            "(id, organization_id, actor_type, action, resource_type, result) "
            "VALUES (:id, :b, 'user', 'x', 'y', 'success')"
        ),
        "INSERT INTO organizations (id, name, slug, default_currency, default_timezone) "
        "VALUES (:b2, 'Evil', 'evil-org', 'AUD', 'UTC')",
    ]
    for sql in statements:
        with pytest.raises(DBAPIError, match="row-level security"), app_engine.begin() as conn:
            _ctx(conn, org=seeded["org_a"], user=seeded["user_a"])
            conn.execute(
                text(sql),
                {
                    "id": str(uuid.uuid4()),
                    "b": seeded["org_b"],
                    "u": seeded["user_a"],
                    "b2": str(uuid.uuid4()),
                },
            )


def test_update_cannot_move_rows_across_tenants(seeded, app_engine):
    with pytest.raises(DBAPIError, match="row-level security"), app_engine.begin() as conn:
        _ctx(conn, org=seeded["org_a"], user=seeded["user_a"])
        conn.execute(text("UPDATE invitations SET organization_id = :b"), {"b": seeded["org_b"]})
    with app_engine.begin() as conn:
        _ctx(conn, org=seeded["org_a"], user=seeded["user_a"])
        updated = conn.execute(
            text("UPDATE organizations SET name = 'pwned' WHERE id = :b"), {"b": seeded["org_b"]}
        )
        assert updated.rowcount == 0


def test_audit_log_is_append_only(seeded, app_engine, settings):
    for sql in ("UPDATE audit_logs SET action = 'tampered'", "DELETE FROM audit_logs"):
        with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as conn:
            _ctx(conn, org=seeded["org_a"], user=seeded["user_a"])
            conn.execute(text(sql))
    system = create_engine(settings.DATABASE_URL_SYSTEM.get_secret_value())
    try:
        with pytest.raises(DBAPIError, match="permission denied"), system.begin() as conn:
            conn.execute(text("DELETE FROM audit_logs"))
    finally:
        system.dispose()


def test_runtime_roles_cannot_read_protected_tables(app_engine, settings, seeded):
    for sql in ("SELECT * FROM email_outbox", "SELECT * FROM security_events"):
        with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as conn:
            conn.execute(text(sql))
    system = create_engine(settings.DATABASE_URL_SYSTEM.get_secret_value())
    try:
        for table in ("users", "organizations", "memberships", "sessions"):
            with pytest.raises(DBAPIError, match="permission denied"), system.begin() as conn:
                conn.execute(text(f"SELECT * FROM {table}"))
    finally:
        system.dispose()


def test_context_does_not_leak_across_pooled_connections(seeded, settings):
    engine = create_engine(
        settings.DATABASE_URL_APP.get_secret_value(), pool_size=1, max_overflow=0
    )
    try:
        with engine.begin() as conn:
            _ctx(conn, org=seeded["org_a"], user=seeded["user_a"])
            assert conn.execute(text("SELECT count(*) FROM organizations")).scalar_one() == 1
        with engine.begin() as conn:  # same physical connection, new transaction
            assert conn.execute(
                text("SELECT current_setting('app.current_org_id', true)")
            ).scalar_one() in (None, "")
            assert conn.execute(text("SELECT count(*) FROM organizations")).scalar_one() == 0
    finally:
        engine.dispose()
