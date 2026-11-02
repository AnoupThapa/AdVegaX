"""Creative engine (Phase 9, task 9-02, PHASE_09_PLAN §6; A27).

* ``creative_sets``, ``creatives`` (versions), ``creative_assets``, ``creative_rules``:
  tenant-owned, forced RLS. The application may read, add and change rows (status, archive),
  never delete them.
* ``campaign_strategies`` gains a unique (organization_id, id) for composite references.
* ``ai_runs.task`` also allows ``creative_copy``.

Revision ID: 0019_creative_engine
Revises: 0018_ai_planner
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy
from sqlalchemy.dialects import postgresql

revision: str = "0019_creative_engine"
down_revision: str | None = "0018_ai_planner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
JSON = postgresql.JSONB(astext_type=sa.Text())


def _now() -> sa.TextClause:
    return sa.text("now()")


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
    op.drop_constraint(op.f("ck_ai_runs_task"), "ai_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_runs_task"), "ai_runs", "task IN ('campaign_strategy', 'creative_copy')"
    )
    op.create_unique_constraint(
        op.f("uq_campaign_strategies_organization_id_id"),
        "campaign_strategies",
        ["organization_id", "id"],
    )
    op.create_table(
        "creative_sets",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=False),
        sa.Column("ai_run_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", TZ, server_default=_now(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "strategy_id"],
            ["campaign_strategies.organization_id", "campaign_strategies.id"],
            name="fk_creative_sets_strategy",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ai_run_id"],
            ["ai_runs.organization_id", "ai_runs.id"],
            name="fk_creative_sets_ai_run",
        ),
        _org_fk("creative_sets"),
        _user_fk("creative_sets", "created_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_creative_sets")),
        sa.UniqueConstraint("organization_id", "id", name="uq_creative_sets_organization_id_id"),
    )
    op.create_index(
        "ix_creative_sets_organization_id_strategy_id",
        "creative_sets",
        ["organization_id", "strategy_id"],
    )
    op.create_table(
        "creative_assets",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", TZ, server_default=_now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=_now(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'archived')", name=op.f("ck_creative_assets_status")
        ),
        sa.CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name=op.f("ck_creative_assets_content_type"),
        ),
        sa.CheckConstraint(
            "width > 0 AND height > 0 AND bytes > 0", name=op.f("ck_creative_assets_size")
        ),
        sa.CheckConstraint("char_length(sha256) = 64", name=op.f("ck_creative_assets_sha256")),
        _org_fk("creative_assets"),
        _user_fk("creative_assets", "uploaded_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_creative_assets")),
        sa.UniqueConstraint("organization_id", "id", name="uq_creative_assets_organization_id_id"),
        sa.UniqueConstraint("storage_key", name="uq_creative_assets_storage_key"),
    )
    op.create_index(
        "ix_creative_assets_organization_id_status",
        "creative_assets",
        ["organization_id", "status"],
    )
    op.create_table(
        "creatives",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("set_id", sa.Uuid(), nullable=False),
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("replaces_id", sa.Uuid(), nullable=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column("angle", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("content", JSON, nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("compliance_notes", JSON, nullable=False),
        sa.Column("checks", JSON, nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", TZ, nullable=True),
        sa.Column("decision_reason", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", TZ, server_default=_now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=_now(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'rejected', 'archived')",
            name=op.f("ck_creatives_status"),
        ),
        sa.CheckConstraint(
            "format IN ('google_rsa', 'meta_single')", name=op.f("ck_creatives_format")
        ),
        sa.CheckConstraint(
            "platform IN ('google_ads', 'meta_ads')", name=op.f("ck_creatives_platform")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_creatives_version")),
        sa.ForeignKeyConstraint(
            ["organization_id", "set_id"],
            ["creative_sets.organization_id", "creative_sets.id"],
            name="fk_creatives_set",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "asset_id"],
            ["creative_assets.organization_id", "creative_assets.id"],
            name="fk_creatives_asset",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "replaces_id"],
            ["creatives.organization_id", "creatives.id"],
            name="fk_creatives_replaces",
        ),
        _org_fk("creatives"),
        _user_fk("creatives", "decided_by"),
        _user_fk("creatives", "created_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_creatives")),
        sa.UniqueConstraint("organization_id", "id", name="uq_creatives_organization_id_id"),
        sa.UniqueConstraint("concept_id", "version", name="uq_creatives_concept_id_version"),
    )
    op.create_index(
        "ix_creatives_organization_id_status", "creatives", ["organization_id", "status"]
    )
    op.create_index("ix_creatives_set_id", "creatives", ["set_id"])
    op.create_index(
        "uq_creatives_one_approved_per_concept",
        "creatives",
        ["concept_id"],
        unique=True,
        postgresql_where=sa.text("status = 'approved'"),
    )
    op.create_table(
        "creative_rules",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("prohibited_terms", JSON, nullable=False),
        sa.Column("allowed_caps", JSON, nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", TZ, server_default=_now(), nullable=False),
        _org_fk("creative_rules"),
        _user_fk("creative_rules", "updated_by"),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_creative_rules")),
    )
    grants = {
        "creative_sets": ("SELECT", "INSERT"),
        "creatives": ("SELECT", "INSERT", "UPDATE"),
        "creative_assets": ("SELECT", "INSERT", "UPDATE"),
        "creative_rules": ("SELECT", "INSERT", "UPDATE"),
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
    op.drop_table("creative_rules")
    op.drop_index("uq_creatives_one_approved_per_concept", table_name="creatives")
    op.drop_index("ix_creatives_set_id", table_name="creatives")
    op.drop_index("ix_creatives_organization_id_status", table_name="creatives")
    op.drop_table("creatives")
    op.drop_index("ix_creative_assets_organization_id_status", table_name="creative_assets")
    op.drop_table("creative_assets")
    op.drop_index("ix_creative_sets_organization_id_strategy_id", table_name="creative_sets")
    op.drop_table("creative_sets")
    op.drop_constraint(
        op.f("uq_campaign_strategies_organization_id_id"), "campaign_strategies", type_="unique"
    )
    op.execute("DELETE FROM ai_runs WHERE task = 'creative_copy'")
    op.drop_constraint(op.f("ck_ai_runs_task"), "ai_runs", type_="check")
    op.create_check_constraint(op.f("ck_ai_runs_task"), "ai_runs", "task IN ('campaign_strategy')")
