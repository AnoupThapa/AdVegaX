"""Durable background-job records with Row-Level Security.

Revision ID: 0006_job_runs
Revises: 0005_integrations
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy

revision: str = "0006_job_runs"
down_revision: str | None = "0005_integrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey(
                "organizations.id",
                ondelete="CASCADE",
                name="fk_job_runs_organization_id_organizations",
            ),
        ),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("subject_type", sa.String(64)),
        sa.Column("subject_id", sa.String(64)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column(
            "requested_by_user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_job_runs_requested_by_user_id_users"
            ),
        ),
        sa.Column("started_at", TZ),
        sa.Column("finished_at", TZ),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'dead')",
            name="ck_job_runs_status",
        ),
    )
    op.create_index("ix_job_runs_status_next_attempt_at", "job_runs", ["status", "next_attempt_at"])
    op.create_index(
        "ix_job_runs_organization_id_created_at", "job_runs", ["organization_id", "created_at"]
    )
    op.create_index("ix_job_runs_requested_by_user_id", "job_runs", ["requested_by_user_id"])

    enable_rls("job_runs")
    op.execute("GRANT SELECT, INSERT, UPDATE ON job_runs TO advegax_app")
    op.execute("GRANT SELECT, UPDATE ON job_runs TO advegax_system")
    for command in ("SELECT", "INSERT", "UPDATE"):
        kwargs = {}
        if command in ("SELECT", "UPDATE"):
            kwargs["using"] = f"organization_id = {CURRENT_ORG}"
        if command in ("INSERT", "UPDATE"):
            kwargs["check"] = f"organization_id = {CURRENT_ORG}"
        policy(
            "job_runs", f"job_runs_{command.lower()}", command=command, role="advegax_app", **kwargs
        )
    # The worker claims, schedules and recovers jobs across tenants; it never reads tenant data here.
    policy(
        "job_runs", "job_runs_system_select", command="SELECT", role="advegax_system", using="true"
    )
    policy(
        "job_runs",
        "job_runs_system_update",
        command="UPDATE",
        role="advegax_system",
        using="true",
        check="true",
    )


def downgrade() -> None:
    op.drop_table("job_runs")
