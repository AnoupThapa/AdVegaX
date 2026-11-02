"""AI campaign planner (Phase 8, task 8-02, PHASE_08_PLAN §6; A26).

* ``ai_models``, ``prompt_versions``: reference data (which model, which prompt version). Not
  tenant data: the application role may read and add rows (the first time a model or prompt
  version is used), never change or delete them. No RLS: nothing in them belongs to an
  organization.
* ``ai_runs``: every model call — model, prompt version, the data snapshot sent (AdVegaX's own
  aggregated figures), outcome, rejection reasons, tokens, estimated cost, time. Tenant-owned,
  forced RLS. Runs are never deleted by the application (they are the trace behind a strategy).
* ``campaign_strategies``: validated strategies with their budget and computed amounts.
  Tenant-owned, forced RLS.

Revision ID: 0018_ai_planner
Revises: 0017_funnel
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy
from sqlalchemy.dialects import postgresql

revision: str = "0018_ai_planner"
down_revision: str | None = "0017_funnel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "ai_models",
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("created_at", TZ, server_default=_now(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_models")),
        sa.UniqueConstraint("provider", "model_name", name="uq_ai_models_provider_model"),
    )
    op.create_table(
        "prompt_versions",
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("template_hash", sa.String(64), nullable=False),
        sa.Column("created_at", TZ, server_default=_now(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "char_length(template_hash) = 64", name=op.f("ck_prompt_versions_template_hash")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_versions")),
        sa.UniqueConstraint("name", "version", name="uq_prompt_versions_name_version"),
    )
    op.create_table(
        "ai_runs",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=False),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("context_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rejection_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="1", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_cost", sa.Numeric(14, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", TZ, server_default=_now(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'rejected', 'failed', 'timed_out')",
            name=op.f("ck_ai_runs_status"),
        ),
        sa.CheckConstraint("task IN ('campaign_strategy')", name=op.f("ck_ai_runs_task")),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0", name=op.f("ck_ai_runs_tokens")
        ),
        sa.CheckConstraint("attempts BETWEEN 1 AND 5", name=op.f("ck_ai_runs_attempts")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_ai_runs_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_ai_runs_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["ai_models.id"], name=op.f("fk_ai_runs_model_id_ai_models")
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_ai_runs_prompt_version_id_prompt_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_runs")),
        sa.UniqueConstraint("organization_id", "id", name="uq_ai_runs_organization_id_id"),
    )
    op.create_index(
        "ix_ai_runs_organization_id_created_at", "ai_runs", ["organization_id", "created_at"]
    )
    op.create_table(
        "campaign_strategies",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("ai_run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("budget_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("budget_period", sa.String(16), nullable=False),
        sa.Column("budget_currency", sa.String(3), nullable=False),
        sa.Column("budget_amounts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("edited_by", sa.Uuid(), nullable=True),
        sa.Column("edited_at", TZ, nullable=True),
        sa.Column("created_at", TZ, server_default=_now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=_now(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'ready', 'archived')", name=op.f("ck_campaign_strategies_status")
        ),
        sa.CheckConstraint(
            "budget_period IN ('daily', 'monthly')",
            name=op.f("ck_campaign_strategies_budget_period"),
        ),
        sa.CheckConstraint("budget_amount > 0", name=op.f("ck_campaign_strategies_budget_amount")),
        sa.CheckConstraint(
            "char_length(budget_currency) = 3", name=op.f("ck_campaign_strategies_budget_currency")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["products.organization_id", "products.id"],
            name="fk_campaign_strategies_product",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ai_run_id"],
            ["ai_runs.organization_id", "ai_runs.id"],
            name="fk_campaign_strategies_ai_run",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_campaign_strategies_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_campaign_strategies_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["edited_by"],
            ["users.id"],
            name=op.f("fk_campaign_strategies_edited_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_strategies")),
    )
    op.create_index(
        "ix_campaign_strategies_organization_id_status",
        "campaign_strategies",
        ["organization_id", "status"],
    )
    for table in ("ai_models", "prompt_versions"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO advegax_app")
    # A run is written once and never changed or deleted by the application; strategies are
    # edited and archived, never deleted.
    grants = {
        "ai_runs": ("SELECT", "INSERT"),
        "campaign_strategies": ("SELECT", "INSERT", "UPDATE"),
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


def downgrade() -> None:
    op.drop_index("ix_campaign_strategies_organization_id_status", table_name="campaign_strategies")
    op.drop_table("campaign_strategies")
    op.drop_index("ix_ai_runs_organization_id_created_at", table_name="ai_runs")
    op.drop_table("ai_runs")
    op.drop_table("prompt_versions")
    op.drop_table("ai_models")
