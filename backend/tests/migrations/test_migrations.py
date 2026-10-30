"""Migration verification (PHASE_01A_PLAN §16.3) on a dedicated database."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.db.models import Base
from sqlalchemy import create_engine, inspect, text

from tests.conftest import PG_HOST, PG_PORT, alembic_config

MIGRATION_DB = "advegax_migration_test"
URL = f"postgresql+psycopg://advegax_migrator:advegax_migrator@{PG_HOST}:{PG_PORT}/{MIGRATION_DB}"


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(URL)
    yield eng
    eng.dispose()


def test_upgrade_downgrade_upgrade(engine):
    cfg = alembic_config(URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert tables == set()
    command.upgrade(cfg, "head")
    assert set(inspect(engine).get_table_names()) >= set(Base.metadata.tables)


def test_models_match_migrations(engine):
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_every_tenant_table_has_forced_rls_and_policies(engine):
    with engine.connect() as conn:
        tenant_tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = 'organization_id' "
                    "AND table_name NOT IN ('user_action_tokens')"
                )
            )
        }
        tenant_tables.add("organizations")
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "(SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r'"
            )
        ).all()
    status = {name: (enabled, forced, policies) for name, enabled, forced, policies in rows}
    for table in tenant_tables:
        enabled, forced, policies = status[table]
        assert enabled and forced and policies > 0, table


def test_runtime_roles_are_least_privileged(engine):
    with engine.connect() as conn:
        roles = conn.execute(
            text(
                "SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles "
                "WHERE rolname IN ('advegax_app', 'advegax_system', 'advegax_migrator')"
            )
        ).all()
        owners = {
            r[0]
            for r in conn.execute(
                text("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'public'")
            )
        }
        audit_grants = {
            (r[0], r[1])
            for r in conn.execute(
                text(
                    "SELECT grantee, privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_name = 'audit_logs'"
                )
            )
        }
    assert len(roles) == 3
    for name, superuser, bypass, createdb, createrole in roles:
        assert not (superuser or bypass or createdb or createrole), name
    assert owners == {"advegax_migrator"}
    assert not any(
        priv in ("UPDATE", "DELETE", "TRUNCATE") and grantee != "advegax_migrator"
        for grantee, priv in audit_grants
    )
