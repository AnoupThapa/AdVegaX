"""Agency mode (Phase 14, task 14-01, PHASE_14_PLAN §3; A33).

* ``organizations.agency_code``: the code an agency shares with its clients (unique, random,
  regenerable). The system role may read ``id, name, status, agency_code`` (finding an
  agency by its code, and naming the other side of a grant) — nothing else.
* ``agency_grants``: a client organization's grant to an agency organization, with the
  granted role (manager | analyst | viewer) and status (pending | active | revoked).
  Forced RLS: visible to the client and the agency organization, and to active members of
  the agency (the tenant check finds their grants before any organization is chosen). Only
  the client inserts; either side updates.

Revision ID: 0025_agency
Revises: 0024_billing
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, CURRENT_USER, enable_rls, policy

revision: str = "0025_agency"
down_revision: str | None = "0024_billing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
EITHER_SIDE = f"organization_id = {CURRENT_ORG} OR agency_organization_id = {CURRENT_ORG}"
AGENCY_MEMBER = (
    "EXISTS (SELECT 1 FROM memberships m WHERE m.organization_id = "
    f"agency_grants.agency_organization_id AND m.user_id = {CURRENT_USER} "
    "AND m.status = 'active')"
)


def upgrade() -> None:
    op.add_column("organizations", sa.Column("agency_code", sa.String(16), nullable=True))
    op.create_unique_constraint("uq_organizations_agency_code", "organizations", ["agency_code"])
    op.execute("GRANT SELECT (id, name, status, agency_code) ON organizations TO advegax_system")
    policy(
        "organizations",
        "organizations_system_select",
        command="SELECT",
        role="advegax_system",
        using="true",
    )

    op.create_table(
        "agency_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agency_organization_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("accepted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", TZ, server_default=sa.text("now()"), nullable=False),
        sa.Column("accepted_at", TZ, nullable=True),
        sa.Column("revoked_at", TZ, nullable=True),
        sa.CheckConstraint(
            "role IN ('manager', 'analyst', 'viewer')", name=op.f("ck_agency_grants_role")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'revoked')", name=op.f("ck_agency_grants_status")
        ),
        sa.CheckConstraint(
            "organization_id <> agency_organization_id", name=op.f("ck_agency_grants_other")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_agency_grants_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agency_organization_id"],
            ["organizations.id"],
            name=op.f("fk_agency_grants_agency_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agency_grants")),
    )
    op.create_index(
        "uq_agency_grants_open",
        "agency_grants",
        ["organization_id", "agency_organization_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'revoked'"),
    )
    op.create_index(
        "ix_agency_grants_agency_organization_id", "agency_grants", ["agency_organization_id"]
    )
    enable_rls("agency_grants")
    op.execute("GRANT SELECT, INSERT, UPDATE ON agency_grants TO advegax_app")
    policy(
        "agency_grants",
        "agency_grants_select",
        command="SELECT",
        role="advegax_app",
        using=f"{EITHER_SIDE} OR {AGENCY_MEMBER}",
    )
    policy(
        "agency_grants",
        "agency_grants_insert",
        command="INSERT",
        role="advegax_app",
        check=f"organization_id = {CURRENT_ORG}",
    )
    policy(
        "agency_grants",
        "agency_grants_update",
        command="UPDATE",
        role="advegax_app",
        using=EITHER_SIDE,
        check=EITHER_SIDE,
    )


def downgrade() -> None:
    op.drop_table("agency_grants")
    op.execute("DROP POLICY IF EXISTS organizations_system_select ON organizations")
    op.execute("REVOKE SELECT (id, name, status, agency_code) ON organizations FROM advegax_system")
    op.drop_constraint("uq_organizations_agency_code", "organizations", type_="unique")
    op.drop_column("organizations", "agency_code")
