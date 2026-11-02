"""Organizations, memberships, invitations with Row-Level Security.

Revision ID: 0002_organizations
Revises: 0001_identity
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, CURRENT_USER, enable_rls, policy

revision: str = "0002_organizations"
down_revision: str | None = "0001_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
ROLE_CHECK = "role IN ('owner', 'admin', 'manager', 'analyst', 'viewer')"


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("default_currency", sa.String(3), nullable=False),
        sa.Column("default_timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_organizations_created_by_user_id_users"
            ),
        ),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "default_currency ~ '^[A-Z]{3}$'", name="ck_organizations_currency_iso4217"
        ),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_organizations_status"),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_organizations_slug_format"
        ),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_index("ix_organizations_created_by_user_id", "organizations", ["created_by_user_id"])

    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey(
                "organizations.id",
                ondelete="CASCADE",
                name="fk_memberships_organization_id_organizations",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_memberships_user_id_users"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id", "user_id", name="uq_memberships_organization_id_user_id"
        ),
        sa.CheckConstraint(ROLE_CHECK, name="ck_memberships_role"),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'removed')", name="ck_memberships_status"
        ),
    )
    op.create_index("ix_memberships_user_id_status", "memberships", ["user_id", "status"])

    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey(
                "organizations.id",
                ondelete="CASCADE",
                name="fk_invitations_organization_id_organizations",
            ),
            nullable=False,
        ),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "invited_by_user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_invitations_invited_by_user_id_users"
            ),
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("accepted_at", TZ),
        sa.Column(
            "accepted_by_user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_invitations_accepted_by_user_id_users"
            ),
        ),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(ROLE_CHECK, name="ck_invitations_role"),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')", name="ck_invitations_status"
        ),
        sa.CheckConstraint("email = lower(email)", name="ck_invitations_email_lowercase"),
    )
    op.create_index(
        "ix_invitations_organization_id_status", "invitations", ["organization_id", "status"]
    )
    op.create_index("ix_invitations_invited_by_user_id", "invitations", ["invited_by_user_id"])
    op.create_index("ix_invitations_accepted_by_user_id", "invitations", ["accepted_by_user_id"])
    op.create_index(
        "uq_invitations_pending_email",
        "invitations",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    # Invitation tokens reference the organization and invitation (global token table, no RLS).
    op.add_column(
        "user_action_tokens",
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey(
                "organizations.id",
                ondelete="CASCADE",
                name="fk_user_action_tokens_organization_id_organizations",
            ),
        ),
    )
    op.add_column(
        "user_action_tokens",
        sa.Column(
            "invitation_id",
            sa.Uuid(),
            sa.ForeignKey(
                "invitations.id",
                ondelete="CASCADE",
                name="fk_user_action_tokens_invitation_id_invitations",
            ),
        ),
    )
    op.create_index(
        "ix_user_action_tokens_organization_id", "user_action_tokens", ["organization_id"]
    )
    op.create_index("ix_user_action_tokens_invitation_id", "user_action_tokens", ["invitation_id"])

    # --- Row-Level Security --------------------------------------------------------
    for table in ("organizations", "memberships", "invitations"):
        enable_rls(table)

    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON organizations, memberships, invitations TO advegax_app"
    )

    active_member = (
        "EXISTS (SELECT 1 FROM memberships m WHERE m.organization_id = organizations.id "
        f"AND m.user_id = {CURRENT_USER} AND m.status = 'active')"
    )
    policy(
        "organizations",
        "organizations_select",
        command="SELECT",
        role="advegax_app",
        using=f"id = {CURRENT_ORG} OR {active_member}",
    )
    policy(
        "organizations",
        "organizations_insert",
        command="INSERT",
        role="advegax_app",
        check=f"id = {CURRENT_ORG}",
    )
    policy(
        "organizations",
        "organizations_update",
        command="UPDATE",
        role="advegax_app",
        using=f"id = {CURRENT_ORG}",
        check=f"id = {CURRENT_ORG}",
    )

    policy(
        "memberships",
        "memberships_select",
        command="SELECT",
        role="advegax_app",
        using=f"organization_id = {CURRENT_ORG} OR user_id = {CURRENT_USER}",
    )
    policy(
        "memberships",
        "memberships_insert",
        command="INSERT",
        role="advegax_app",
        check=f"organization_id = {CURRENT_ORG}",
    )
    policy(
        "memberships",
        "memberships_update",
        command="UPDATE",
        role="advegax_app",
        using=f"organization_id = {CURRENT_ORG}",
        check=f"organization_id = {CURRENT_ORG}",
    )

    for command in ("SELECT", "INSERT", "UPDATE"):
        kwargs = {}
        if command in ("SELECT", "UPDATE"):
            kwargs["using"] = f"organization_id = {CURRENT_ORG}"
        if command in ("INSERT", "UPDATE"):
            kwargs["check"] = f"organization_id = {CURRENT_ORG}"
        policy(
            "invitations",
            f"invitations_{command.lower()}",
            command=command,
            role="advegax_app",
            **kwargs,
        )


def downgrade() -> None:
    op.drop_index("ix_user_action_tokens_invitation_id", table_name="user_action_tokens")
    op.drop_index("ix_user_action_tokens_organization_id", table_name="user_action_tokens")
    op.drop_column("user_action_tokens", "invitation_id")
    op.drop_column("user_action_tokens", "organization_id")
    op.execute("DROP POLICY IF EXISTS organizations_select ON organizations")
    op.drop_table("invitations")
    op.drop_table("memberships")
    op.drop_table("organizations")
