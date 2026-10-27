"""Optimization engine (Phase 11, task 11-02, PHASE_11_PLAN §5; A30).

* ``recommendations``, ``recommendation_outcomes`` and ``optimization_settings``: tenant-owned,
  forced RLS; read, add, change (outcomes: read and add) — never deleted. At most one open
  recommendation per campaign and kind (partial unique index on the fingerprint).
* ``actions.recommendation_id``: the recommendation a change was made from; required exactly
  when ``source = 'recommendation'``.
* ``ai_runs.task`` also allows ``optimization``.

Revision ID: 0022_optimization
Revises: 0021_campaign_builder
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy
from sqlalchemy.dialects import postgresql

revision: str = "0022_optimization"
down_revision: str | None = "0021_campaign_builder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
JSON = postgresql.JSONB(astext_type=sa.Text())
KINDS = "'spend_without_results', 'losing_money', 'budget_limited', 'cost_jump', 'funnel_drop'"
STATUSES = "'open', 'approved', 'rejected', 'done', 'expired', 'out_of_date', 'superseded'"
REASONS = "'not_relevant', 'figures_wrong', 'wrong_time', 'other'"


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


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("ad_account_id", sa.Uuid(), nullable=True),
        sa.Column("signal", JSON, nullable=False),
        sa.Column("proposal", JSON, nullable=False),
        sa.Column("prechecks", JSON, nullable=False),
        sa.Column("campaign_state", JSON, nullable=False),
        sa.Column("explanation", sa.String(1200), nullable=False),
        sa.Column("confidence", sa.String(8), nullable=False),
        sa.Column("assumptions", JSON, nullable=False),
        sa.Column("risks", JSON, nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("explained_by", sa.String(8), nullable=False),
        sa.Column("ai_run_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("fingerprint", sa.String(200), nullable=False),
        sa.Column("closed_reason", sa.String(64), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", TZ, nullable=True),
        sa.Column("decision_reason", sa.String(32), nullable=True),
        sa.Column("decision_note", sa.String(500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TZ, server_default=_now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=_now(), nullable=False),
        sa.CheckConstraint(f"kind IN ({KINDS})", name=op.f("ck_recommendations_kind")),
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f("ck_recommendations_status")),
        sa.CheckConstraint(
            "confidence IN ('low', 'medium', 'high')", name=op.f("ck_recommendations_confidence")
        ),
        sa.CheckConstraint(
            "explained_by IN ('ai', 'rules')", name=op.f("ck_recommendations_explained_by")
        ),
        sa.CheckConstraint(
            f"decision_reason IS NULL OR decision_reason IN ({REASONS})",
            name=op.f("ck_recommendations_decision_reason"),
        ),
        sa.CheckConstraint("rank >= 1", name=op.f("ck_recommendations_rank")),
        sa.CheckConstraint(
            "campaign_id IS NOT NULL OR kind = 'funnel_drop'",
            name=op.f("ck_recommendations_campaign"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["ad_campaigns.organization_id", "ad_campaigns.id"],
            name="fk_recommendations_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ad_account_id"],
            ["ad_accounts.organization_id", "ad_accounts.id"],
            name="fk_recommendations_ad_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ai_run_id"],
            ["ai_runs.organization_id", "ai_runs.id"],
            name="fk_recommendations_ai_run",
        ),
        _org_fk("recommendations"),
        _user_fk("recommendations", "decided_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
        sa.UniqueConstraint("organization_id", "id", name="uq_recommendations_organization_id_id"),
    )
    op.create_index(
        "ix_recommendations_organization_id_status",
        "recommendations",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_recommendations_organization_id_campaign_id",
        "recommendations",
        ["organization_id", "campaign_id"],
    )
    op.create_index(
        "uq_recommendations_one_open",
        "recommendations",
        ["organization_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "recommendation_outcomes",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("after_days", sa.Integer(), nullable=False),
        sa.Column("before", JSON, nullable=False),
        sa.Column("after", JSON, nullable=False),
        sa.Column("created_at", TZ, server_default=_now(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "after_days IN (7, 14)", name=op.f("ck_recommendation_outcomes_after_days")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "recommendation_id"],
            ["recommendations.organization_id", "recommendations.id"],
            name="fk_recommendation_outcomes_recommendation",
            ondelete="CASCADE",
        ),
        _org_fk("recommendation_outcomes"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation_outcomes")),
        sa.UniqueConstraint(
            "recommendation_id", "after_days", name="uq_recommendation_outcomes_after"
        ),
    )
    op.create_table(
        "optimization_settings",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("min_spend", sa.Numeric(20, 6), nullable=False),
        sa.Column("min_conversions", sa.Integer(), nullable=False),
        sa.Column("budget_step_percent", sa.Integer(), nullable=False),
        sa.Column("cost_jump_percent", sa.Integer(), nullable=False),
        sa.Column("last_run_on", sa.Date(), nullable=True),
        sa.Column("refreshes_on", sa.Date(), nullable=True),
        sa.Column("refreshes_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_run_summary", JSON, nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", TZ, server_default=_now(), nullable=False),
        sa.CheckConstraint("min_spend > 0", name=op.f("ck_optimization_settings_min_spend")),
        sa.CheckConstraint(
            "min_conversions >= 1", name=op.f("ck_optimization_settings_min_conversions")
        ),
        sa.CheckConstraint(
            "budget_step_percent BETWEEN 5 AND 50",
            name=op.f("ck_optimization_settings_budget_step_percent"),
        ),
        sa.CheckConstraint(
            "cost_jump_percent BETWEEN 10 AND 200",
            name=op.f("ck_optimization_settings_cost_jump_percent"),
        ),
        sa.CheckConstraint(
            "refreshes_used >= 0", name=op.f("ck_optimization_settings_refreshes_used")
        ),
        _org_fk("optimization_settings"),
        _user_fk("optimization_settings", "updated_by"),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_optimization_settings")),
    )
    grants = {
        "recommendations": ("SELECT", "INSERT", "UPDATE"),
        "recommendation_outcomes": ("SELECT", "INSERT"),
        "optimization_settings": ("SELECT", "INSERT", "UPDATE"),
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

    op.add_column("actions", sa.Column("recommendation_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_actions_recommendation",
        "actions",
        "recommendations",
        ["organization_id", "recommendation_id"],
        ["organization_id", "id"],
    )
    op.create_check_constraint(
        op.f("ck_actions_recommendation_source"),
        "actions",
        "(recommendation_id IS NULL) = (source = 'user')",
    )
    op.create_index("ix_actions_recommendation_id", "actions", ["recommendation_id"])

    op.drop_constraint(op.f("ck_ai_runs_task"), "ai_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_runs_task"),
        "ai_runs",
        "task IN ('campaign_strategy', 'creative_copy', 'optimization')",
    )


def downgrade() -> None:
    op.execute("UPDATE recommendations SET ai_run_id = NULL")
    op.execute("DELETE FROM ai_runs WHERE task = 'optimization'")
    op.drop_constraint(op.f("ck_ai_runs_task"), "ai_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_runs_task"), "ai_runs", "task IN ('campaign_strategy', 'creative_copy')"
    )
    op.execute("DELETE FROM actions WHERE recommendation_id IS NOT NULL")
    op.drop_index("ix_actions_recommendation_id", table_name="actions")
    op.drop_constraint(op.f("ck_actions_recommendation_source"), "actions", type_="check")
    op.drop_constraint("fk_actions_recommendation", "actions", type_="foreignkey")
    op.drop_column("actions", "recommendation_id")
    op.drop_table("optimization_settings")
    op.drop_table("recommendation_outcomes")
    op.drop_index("uq_recommendations_one_open", table_name="recommendations")
    op.drop_index("ix_recommendations_organization_id_campaign_id", table_name="recommendations")
    op.drop_index("ix_recommendations_organization_id_status", table_name="recommendations")
    op.drop_table("recommendations")
