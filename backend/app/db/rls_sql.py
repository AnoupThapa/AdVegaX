"""Shared SQL fragments for Row-Level Security in migrations (DATABASE_SCHEMA §19)."""

from __future__ import annotations

from alembic import op

CURRENT_ORG = "NULLIF(current_setting('app.current_org_id', true), '')::uuid"
CURRENT_USER = "NULLIF(current_setting('app.current_user_id', true), '')::uuid"


def require_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF (SELECT count(*) FROM pg_roles
              WHERE rolname IN ('advegax_app', 'advegax_system')) <> 2 THEN
            RAISE EXCEPTION 'Database roles advegax_app and advegax_system must exist before '
                            'migrating (see infrastructure/docker/postgres/init/001_roles.sql)';
          END IF;
        END
        $$;
        """
    )


def enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def policy(
    table: str,
    name: str,
    *,
    command: str,
    role: str,
    using: str | None = None,
    check: str | None = None,
) -> None:
    sql = f"CREATE POLICY {name} ON {table} AS PERMISSIVE FOR {command} TO {role}"
    if using is not None:
        sql += f" USING ({using})"
    if check is not None:
        sql += f" WITH CHECK ({check})"
    op.execute(sql)
