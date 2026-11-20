"""Identity: users, password credentials, sessions, single-use action tokens.

Global identity tables are not tenant-owned and have no RLS (DATABASE_SCHEMA §19);
they are reachable only through the identity domain.

Revision ID: 0001_identity
Revises:
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import require_roles

revision: str = "0001_identity"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    require_roles()
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("display_name", sa.String(120)),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("email_verified_at", TZ),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "user_password_credentials",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="CASCADE", name="fk_user_password_credentials_user_id_users"
            ),
            primary_key=True,
        ),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("password_changed_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_sessions_user_id_users"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("auth_method", sa.String(32), nullable=False, server_default="password"),
        sa.Column("assurance_level", sa.String(32), nullable=False, server_default="single_factor"),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("last_used_at", TZ, nullable=False),
        sa.Column("idle_expires_at", TZ, nullable=False),
        sa.Column("absolute_expires_at", TZ, nullable=False),
        sa.Column("revoked_at", TZ),
        sa.Column("revoked_reason", sa.String(64)),
        sa.Column("ip_hash", sa.String(64)),
        sa.Column("user_agent_summary", sa.String(200)),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at", name="ck_sessions_idle_within_absolute"
        ),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index(
        "ix_sessions_user_id_active",
        "sessions",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "user_action_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="CASCADE", name="fk_user_action_tokens_user_id_users"
            ),
        ),
        sa.Column("email", sa.String(254)),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("consumed_at", TZ),
        sa.Column("invalidated_at", TZ),
        sa.Column("created_at", TZ, nullable=False),
        sa.CheckConstraint(
            "purpose IN ('email_verification', 'password_reset', 'invitation')",
            name="ck_user_action_tokens_purpose",
        ),
        sa.UniqueConstraint("token_hash", name="uq_user_action_tokens_token_hash"),
    )
    op.create_index(
        "ix_user_action_tokens_user_id_purpose", "user_action_tokens", ["user_id", "purpose"]
    )

    for table in ("users", "user_password_credentials", "sessions", "user_action_tokens"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO advegax_app")


def downgrade() -> None:
    op.drop_table("user_action_tokens")
    op.drop_table("sessions")
    op.drop_table("user_password_credentials")
    op.drop_table("users")
