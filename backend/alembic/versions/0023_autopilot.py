"""Controlled autopilot (Phase 12, task 12-02, PHASE_12_PLAN §5; A31).

* ``autopilot_policies`` (read, add, change) and ``autopilot_runs`` (read, add): tenant-owned,
  forced RLS — never deleted.
* ``actions.source`` also allows ``autopilot``; ``actions.policy`` keeps the policy snapshot
  that allowed an automatic change (set exactly for those).
* ``audit_logs.actor_type`` also allows ``autopilot``.

Revision ID: 0023_autopilot
Revises: 0022_optimization
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy
from sqlalchemy.dialects import postgresql

revision: str = "0023_autopilot"
down_revision: str | None = "0022_optimization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
JSON = postgresql.JSONB(astext_type=sa.Text())
ACTORS = "'user', 'system', 'worker', 'ai_recommendation'"


def _org_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
        ondelete="CASCADE",
    )


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="SET NULL"
    )


def upgrade() -> None:
    op.create_table(
        "autopilot_policies",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("enabled_by", sa.Uuid(), nullable=True),
        sa.Column("enabled_at", TZ, nullable=True),
        sa.Column("stopped_by", sa.Uuid(), nullable=True),
        sa.Column("stopped_at", TZ, nullable=True),
        sa.Column("stopped_reason", sa.String(64), nullable=True),
        sa.Column("kinds", JSON, server_default="[]", nullable=False),
        sa.Column("ad_account_ids", JSON, server_default="[]", nullable=False),
        sa.Column("excluded_campaign_ids", JSON, server_default="[]", nullable=False),
        sa.Column("max_changes_per_day", sa.Integer(), nullable=False),
        sa.Column("campaign_cooldown_days", sa.Integer(), nullable=False),
        sa.Column("max_decrease_percent", sa.Integer(), nullable=False),
        sa.Column("max_cumulative_decrease_percent", sa.Integer(), nullable=False),
        sa.Column("cumulative_window_days", sa.Integer(), nullable=False),
        sa.Column("min_campaign_age_days", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", TZ, server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "max_changes_per_day >= 1", name=op.f("ck_autopilot_policies_max_changes_per_day")
        ),
        sa.CheckConstraint(
            "campaign_cooldown_days >= 1",
            name=op.f("ck_autopilot_policies_campaign_cooldown_days"),
        ),
        sa.CheckConstraint(
            "max_decrease_percent BETWEEN 1 AND 50",
            name=op.f("ck_autopilot_policies_max_decrease_percent"),
        ),
        sa.CheckConstraint(
            "max_cumulative_decrease_percent BETWEEN 1 AND 90",
            name=op.f("ck_autopilot_policies_max_cumulative_decrease_percent"),
        ),
        sa.CheckConstraint(
            "cumulative_window_days >= 7",
            name=op.f("ck_autopilot_policies_cumulative_window_days"),
        ),
        sa.CheckConstraint(
            "min_campaign_age_days >= 1", name=op.f("ck_autopilot_policies_min_campaign_age_days")
        ),
        _org_fk("autopilot_policies"),
        *(_user_fk("autopilot_policies", c) for c in ("enabled_by", "stopped_by", "updated_by")),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_autopilot_policies")),
    )
    op.create_table(
        "autopilot_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("considered", sa.Integer(), nullable=False),
        sa.Column("made", JSON, nullable=False),
        sa.Column("skipped", JSON, nullable=False),
        sa.Column("limit_reached", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("stopped_reason", sa.String(64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("considered >= 0", name=op.f("ck_autopilot_runs_considered")),
        _org_fk("autopilot_runs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_autopilot_runs")),
    )
    op.create_index(
        "ix_autopilot_runs_organization_id_started_at",
        "autopilot_runs",
        ["organization_id", "started_at"],
    )
    grants = {
        "autopilot_policies": ("SELECT", "INSERT", "UPDATE"),
        "autopilot_runs": ("SELECT", "INSERT"),
    }
    for table, commands in grants.items():
        enable_rls(table)
        op.execute(f"GRANT {', '.join(commands)} ON {table} TO advegax_app")
        for command in commands:
            kwargs = {}
            if command in ("SELECT", "UPDATE"):
                kwargs["using"] = f"organization_id = {CURRENT_ORG}"
            if command in ("INSERT", "UPDATE"):
                kwargs["check"] = f"organization_id = {CURRENT_ORG}"
            policy(
                table, f"{table}_{command.lower()}", command=command, role="advegax_app", **kwargs
            )

    op.add_column("actions", sa.Column("policy", JSON, nullable=True))
    op.drop_constraint(op.f("ck_actions_source"), "actions", type_="check")
    op.create_check_constraint(
        op.f("ck_actions_source"), "actions", "source IN ('user', 'recommendation', 'autopilot')"
    )
    op.create_check_constraint(
        op.f("ck_actions_autopilot_policy"),
        "actions",
        "(policy IS NOT NULL) = (source = 'autopilot')",
    )
    op.drop_constraint("ck_audit_logs_actor_type", "audit_logs", type_="check")
    op.create_check_constraint(
        "ck_audit_logs_actor_type", "audit_logs", f"actor_type IN ({ACTORS}, 'autopilot')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_logs_actor_type", "audit_logs", type_="check")
    op.execute("UPDATE audit_logs SET actor_type = 'system' WHERE actor_type = 'autopilot'")
    op.create_check_constraint(
        "ck_audit_logs_actor_type", "audit_logs", f"actor_type IN ({ACTORS})"
    )
    op.execute("DELETE FROM actions WHERE source = 'autopilot'")
    op.drop_constraint(op.f("ck_actions_autopilot_policy"), "actions", type_="check")
    op.drop_constraint(op.f("ck_actions_source"), "actions", type_="check")
    op.create_check_constraint(
        op.f("ck_actions_source"), "actions", "source IN ('user', 'recommendation')"
    )
    op.drop_column("actions", "policy")
    op.drop_index("ix_autopilot_runs_organization_id_started_at", table_name="autopilot_runs")
    op.drop_table("autopilot_runs")
    op.drop_table("autopilot_policies")
