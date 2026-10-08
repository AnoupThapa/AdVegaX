"""Transactional email outbox. The API inserts; only the system role reads and delivers.

Revision ID: 0004_email_outbox
Revises: 0003_audit_security
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004_email_outbox"
down_revision: str | None = "0003_audit_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey(
                "organizations.id",
                ondelete="SET NULL",
                name="fk_email_outbox_organization_id_organizations",
            ),
        ),
        sa.Column("template", sa.String(64), nullable=False),
        sa.Column("recipient", sa.String(254), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("next_attempt_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("sent_at", TZ),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')", name="ck_email_outbox_status"
        ),
    )
    op.create_index("ix_email_outbox_organization_id", "email_outbox", ["organization_id"])
    op.create_index(
        "ix_email_outbox_status_next_attempt_at", "email_outbox", ["status", "next_attempt_at"]
    )

    enable_rls("email_outbox")
    op.execute("GRANT INSERT ON email_outbox TO advegax_app")
    op.execute("GRANT SELECT, UPDATE ON email_outbox TO advegax_system")
    policy(
        "email_outbox",
        "email_outbox_insert",
        command="INSERT",
        role="advegax_app",
        check=f"organization_id IS NULL OR organization_id = {CURRENT_ORG}",
    )
    policy(
        "email_outbox",
        "email_outbox_system_select",
        command="SELECT",
        role="advegax_system",
        using="true",
    )
    policy(
        "email_outbox",
        "email_outbox_system_update",
        command="UPDATE",
        role="advegax_system",
        using="true",
        check="true",
    )


def downgrade() -> None:
    op.drop_table("email_outbox")
