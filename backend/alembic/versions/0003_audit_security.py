"""Append-only audit log and security events with Row-Level Security.

Revision ID: 0003_audit_security
Revises: 0002_organizations
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003_audit_security"
down_revision: str | None = "0002_organizations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey(
                "organizations.id",
                ondelete="RESTRICT",
                name="fk_audit_logs_organization_id_organizations",
            ),
        ),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_audit_logs_actor_user_id_users"
            ),
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64)),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("before_json", JSONB),
        sa.Column("after_json", JSONB),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system', 'worker', 'ai_recommendation')",
            name="ck_audit_logs_actor_type",
        ),
        sa.CheckConstraint(
            "result IN ('success', 'denied', 'failed')", name="ck_audit_logs_result"
        ),
    )
    op.create_index(
        "ix_audit_logs_organization_id_created_at", "audit_logs", ["organization_id", "created_at"]
    )
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])

    op.create_table(
        "security_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey(
                "organizations.id",
                ondelete="SET NULL",
                name="fk_security_events_organization_id_organizations",
            ),
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_security_events_user_id_users"),
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("ip_hash", sa.String(64)),
        sa.Column("user_agent_summary", sa.String(200)),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_security_events_organization_id", "security_events", ["organization_id"])
    op.create_index(
        "ix_security_events_user_id_created_at", "security_events", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_security_events_event_type_created_at", "security_events", ["event_type", "created_at"]
    )

    enable_rls("audit_logs")
    enable_rls("security_events")

    # Audit log is append-only: no runtime role receives UPDATE or DELETE.
    op.execute("GRANT SELECT, INSERT ON audit_logs TO advegax_app")
    policy(
        "audit_logs",
        "audit_logs_select",
        command="SELECT",
        role="advegax_app",
        using=f"organization_id = {CURRENT_ORG}",
    )
    policy(
        "audit_logs",
        "audit_logs_insert",
        command="INSERT",
        role="advegax_app",
        check=f"organization_id IS NULL OR organization_id = {CURRENT_ORG}",
    )

    # Security events: the API only inserts; reading is a system operation.
    op.execute("GRANT INSERT ON security_events TO advegax_app")
    op.execute("GRANT SELECT ON security_events TO advegax_system")
    policy(
        "security_events",
        "security_events_insert",
        command="INSERT",
        role="advegax_app",
        check=f"organization_id IS NULL OR organization_id = {CURRENT_ORG}",
    )
    policy(
        "security_events",
        "security_events_system_select",
        command="SELECT",
        role="advegax_system",
        using="true",
    )


def downgrade() -> None:
    op.drop_table("security_events")
    op.drop_table("audit_logs")
