"""The Admin portal (Phase 16, tasks 16-03 and 16-04; A35).

* ``platform_admins``: the people who operate this AdVegaX installation (not customers), with
  their two-step sign-in secret, encrypted. System role only.
* ``platform_settings``: keys and switches entered in the Admin portal, each value encrypted
  with the installation's key set (secrets are never read back by the API). System role only.
* The system role may read people's ``id, email, display_name, status, created_at`` and change
  an organization's ``status`` (suspend or reactivate) — for the Admin portal's lists.

Revision ID: 0027_platform_admin
Revises: 0026_retention
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import enable_rls, policy

revision: str = "0027_platform_admin"
down_revision: str | None = "0026_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
USER_COLUMNS = "id, email, display_name, status, created_at"


def _system_only(table: str, commands: tuple[str, ...]) -> None:
    enable_rls(table)
    op.execute(f"GRANT {', '.join(commands)} ON {table} TO advegax_system")
    for command in commands:
        kwargs = {}
        if command in ("SELECT", "UPDATE", "DELETE"):
            kwargs["using"] = "true"
        if command in ("INSERT", "UPDATE"):
            kwargs["check"] = "true"
        policy(
            table,
            f"{table}_system_{command.lower()}",
            command=command,
            role="advegax_system",
            **kwargs,
        )


def upgrade() -> None:
    op.create_table(
        "platform_admins",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("totp_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("totp_wrapped_key", sa.LargeBinary(), nullable=True),
        sa.Column("totp_key_version", sa.Integer(), nullable=True),
        sa.Column("totp_enabled_at", TZ, nullable=True),
        sa.Column("created_at", TZ, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_platform_admins_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_platform_admins")),
    )
    _system_only("platform_admins", ("SELECT", "INSERT", "UPDATE"))
    op.create_table(
        "platform_settings",
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("hint", sa.String(8), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", TZ, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_platform_settings")),
    )
    _system_only("platform_settings", ("SELECT", "INSERT", "UPDATE", "DELETE"))
    op.execute(f"GRANT SELECT ({USER_COLUMNS}) ON users TO advegax_system")
    op.execute("GRANT UPDATE (status) ON organizations TO advegax_system")
    policy(
        "organizations",
        "organizations_system_update",
        command="UPDATE",
        role="advegax_system",
        using="true",
        check="true",
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS organizations_system_update ON organizations")
    op.execute("REVOKE UPDATE (status) ON organizations FROM advegax_system")
    op.execute(f"REVOKE SELECT ({USER_COLUMNS}) ON users FROM advegax_system")
    op.drop_table("platform_settings")
    op.drop_table("platform_admins")
