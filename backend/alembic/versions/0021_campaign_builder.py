"""Campaign builder (Phase 10B, task 10B-02, PHASE_10B_PLAN §5; A29).

* ``campaign_drafts``: tenant-owned, forced RLS; read, add, change — never deleted.
* ``action_settings.landing_domains``: the store's own web addresses for landing pages.
* ``actions``: ``draft_id`` (a draft's launch, go-live and cleanup); ``campaign_id`` may be
  empty for those (the campaign does not exist in AdVegaX yet); three new action types; at
  most one open change per draft.

Revision ID: 0021_campaign_builder
Revises: 0020_action_engine
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy
from sqlalchemy.dialects import postgresql

revision: str = "0021_campaign_builder"
down_revision: str | None = "0020_action_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
JSON = postgresql.JSONB(astext_type=sa.Text())
OLD_TYPES = "'campaign.pause', 'campaign.resume', 'campaign.set_daily_budget'"
DRAFT_TYPES = "'campaign.create', 'campaign.go_live', 'campaign.remove_draft_objects'"
OPEN = "status IN ('pending', 'approved', 'queued', 'submitting', 'unknown')"


def upgrade() -> None:
    op.create_table(
        "campaign_drafts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=False),
        sa.Column("creative_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("ad_account_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("daily_budget", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("locations", JSON, nullable=False),
        sa.Column("age_min", sa.Integer(), server_default="18", nullable=False),
        sa.Column("age_max", sa.Integer(), server_default="65", nullable=False),
        sa.Column("keywords", JSON, nullable=False),
        sa.Column("landing_url", sa.String(2048), nullable=False),
        sa.Column("meta_page_id", sa.String(32), nullable=True),
        sa.Column("meta_pixel_id", sa.String(32), nullable=True),
        sa.Column("declaration_confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("declaration_confirmed_at", TZ, nullable=True),
        sa.Column("reference", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("created_ids", JSON, server_default="{}", nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", TZ, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TZ, server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'launching', 'created', 'live', 'failed', 'archived')",
            name=op.f("ck_campaign_drafts_status"),
        ),
        sa.CheckConstraint(
            "platform IN ('google_ads', 'meta_ads')", name=op.f("ck_campaign_drafts_platform")
        ),
        sa.CheckConstraint("daily_budget > 0", name=op.f("ck_campaign_drafts_daily_budget")),
        sa.CheckConstraint("char_length(currency) = 3", name=op.f("ck_campaign_drafts_currency")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_campaign_drafts_version")),
        sa.CheckConstraint(
            "age_min BETWEEN 18 AND 65 AND age_max BETWEEN age_min AND 65",
            name=op.f("ck_campaign_drafts_age"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "strategy_id"],
            ["campaign_strategies.organization_id", "campaign_strategies.id"],
            name="fk_campaign_drafts_strategy",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "creative_id"],
            ["creatives.organization_id", "creatives.id"],
            name="fk_campaign_drafts_creative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ad_account_id"],
            ["ad_accounts.organization_id", "ad_accounts.id"],
            name="fk_campaign_drafts_ad_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_campaign_drafts_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        *(
            sa.ForeignKeyConstraint(
                [c], ["users.id"], name=op.f(f"fk_campaign_drafts_{c}_users"), ondelete="SET NULL"
            )
            for c in ("declaration_confirmed_by", "created_by", "updated_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_drafts")),
        sa.UniqueConstraint("organization_id", "id", name="uq_campaign_drafts_organization_id_id"),
        sa.UniqueConstraint("reference", name="uq_campaign_drafts_reference"),
    )
    op.create_index(
        "ix_campaign_drafts_organization_id_strategy_id",
        "campaign_drafts",
        ["organization_id", "strategy_id"],
    )
    enable_rls("campaign_drafts")
    op.execute("GRANT SELECT, INSERT, UPDATE ON campaign_drafts TO advegax_app")
    for command in ("SELECT", "INSERT", "UPDATE"):
        kwargs = {}
        if command in ("SELECT", "UPDATE"):
            kwargs["using"] = f"organization_id = {CURRENT_ORG}"
        if command in ("INSERT", "UPDATE"):
            kwargs["check"] = f"organization_id = {CURRENT_ORG}"
        policy(
            "campaign_drafts",
            f"campaign_drafts_{command.lower()}",
            command=command,
            role="advegax_app",
            **kwargs,
        )

    op.add_column(
        "action_settings",
        sa.Column("landing_domains", JSON, server_default="[]", nullable=False),
    )
    op.add_column("actions", sa.Column("draft_id", sa.Uuid(), nullable=True))
    op.alter_column("actions", "campaign_id", nullable=True)
    op.drop_constraint(op.f("ck_actions_action_type"), "actions", type_="check")
    op.create_check_constraint(
        op.f("ck_actions_action_type"), "actions", f"action_type IN ({OLD_TYPES}, {DRAFT_TYPES})"
    )
    op.create_check_constraint(
        op.f("ck_actions_draft_actions"),
        "actions",
        f"(draft_id IS NULL) <> (action_type IN ({DRAFT_TYPES}))",
    )
    op.create_check_constraint(
        op.f("ck_actions_campaign"),
        "actions",
        f"campaign_id IS NOT NULL OR action_type IN ({DRAFT_TYPES})",
    )
    op.create_foreign_key(
        "fk_actions_draft",
        "actions",
        "campaign_drafts",
        ["organization_id", "draft_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "uq_actions_one_open_per_draft",
        "actions",
        ["draft_id"],
        unique=True,
        postgresql_where=sa.text(OPEN),
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM actions WHERE action_type IN ({DRAFT_TYPES})")
    op.drop_index("uq_actions_one_open_per_draft", table_name="actions")
    op.drop_constraint("fk_actions_draft", "actions", type_="foreignkey")
    op.drop_constraint(op.f("ck_actions_campaign"), "actions", type_="check")
    op.drop_constraint(op.f("ck_actions_draft_actions"), "actions", type_="check")
    op.drop_constraint(op.f("ck_actions_action_type"), "actions", type_="check")
    op.create_check_constraint(
        op.f("ck_actions_action_type"), "actions", f"action_type IN ({OLD_TYPES})"
    )
    op.alter_column("actions", "campaign_id", nullable=False)
    op.drop_column("actions", "draft_id")
    op.drop_column("action_settings", "landing_domains")
    op.drop_index("ix_campaign_drafts_organization_id_strategy_id", table_name="campaign_drafts")
    op.drop_table("campaign_drafts")
