"""Platform-neutral advertising model (Phase 3, task 3-02, PHASE_03_PLAN §8).

Adds ad accounts (extension of ``ad_account`` resources), budgets, campaigns, ad groups, ads,
daily performance and per-account sync state, designed for Google Ads and Meta. Additive only.
Every table is tenant-owned: composite tenant keys, forced RLS and app-role policies (DELETE
included, for re-imports and erasure), as for the commerce tables (0007).

``external_resources`` gains three discovery details for any provider: ``unavailable_reason``
(why an account cannot be linked, e.g. a manager or cancelled account), ``group_path`` (the
groups it sits in, for display) and ``access_hint`` (an opaque, non-secret value needed to reach
it — Google Ads: the manager account to sign in through).

Revision ID: 0012_advertising
Revises: 0011_finance_other_currency
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy
from sqlalchemy.dialects import postgresql

revision: str = "0012_advertising"
down_revision: str | None = "0011_finance_other_currency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "ad_accounts",
    "ad_budgets",
    "ad_campaigns",
    "ad_groups",
    "ads",
    "ad_performance_daily",
    "ad_sync_state",
)


def _security() -> None:
    for table in TENANT_TABLES:
        enable_rls(table)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO advegax_app")
        for command in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            kwargs = {}
            if command in ("SELECT", "UPDATE", "DELETE"):
                kwargs["using"] = f"organization_id = {CURRENT_ORG}"
            if command in ("INSERT", "UPDATE"):
                kwargs["check"] = f"organization_id = {CURRENT_ORG}"
            policy(
                table, f"{table}_{command.lower()}", command=command, role="advegax_app", **kwargs
            )


def upgrade() -> None:
    # Discovery details on resources (any provider): why an account cannot be linked, the
    # groups it sits in (display) and an opaque, non-secret value needed to reach it.
    op.add_column("external_resources", sa.Column("unavailable_reason", sa.String(64)))
    op.add_column("external_resources", sa.Column("group_path", sa.String(1024)))
    op.add_column("external_resources", sa.Column("access_hint", sa.String(255)))
    op.create_table(
        "ad_accounts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("external_resource_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="importing", nullable=False),
        sa.Column("platform_status", sa.String(length=16), nullable=False),
        sa.Column("history_from", sa.Date(), nullable=True),
        sa.Column("first_import_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_code", sa.String(length=64), nullable=True),
        sa.Column("health_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "platform_status IN ('active', 'not_enabled', 'cancelled', 'suspended', 'closed')",
            name=op.f("ck_ad_accounts_platform_status"),
        ),
        sa.CheckConstraint(
            "status IN ('importing', 'active', 'disconnected', 'error')",
            name=op.f("ck_ad_accounts_status"),
        ),
        sa.CheckConstraint("char_length(currency) = 3", name=op.f("ck_ad_accounts_currency")),
        sa.ForeignKeyConstraint(
            ["organization_id", "external_resource_id"],
            ["external_resources.organization_id", "external_resources.id"],
            name="fk_ad_accounts_external_resource",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ad_accounts")),
        sa.UniqueConstraint("external_resource_id", name="uq_ad_accounts_external_resource_id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_ad_accounts_organization_id_id"),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "external_account_id",
            name="uq_ad_accounts_organization_id_provider_external_account_id",
        ),
    )
    op.create_table(
        "ad_budgets",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("ad_account_id", sa.Uuid(), nullable=False),
        sa.Column("external_budget_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("shared", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("level IN ('campaign', 'ad_group')", name=op.f("ck_ad_budgets_level")),
        sa.CheckConstraint("period IN ('daily', 'lifetime')", name=op.f("ck_ad_budgets_period")),
        sa.CheckConstraint("amount IS NULL OR amount >= 0", name=op.f("ck_ad_budgets_amount")),
        sa.CheckConstraint("char_length(currency) = 3", name=op.f("ck_ad_budgets_currency")),
        sa.ForeignKeyConstraint(
            ["organization_id", "ad_account_id"],
            ["ad_accounts.organization_id", "ad_accounts.id"],
            name="fk_ad_budgets_ad_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ad_budgets")),
        sa.UniqueConstraint(
            "ad_account_id",
            "external_budget_id",
            name="uq_ad_budgets_ad_account_id_external_budget_id",
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_ad_budgets_organization_id_id"),
    )
    op.create_table(
        "ad_sync_state",
        sa.Column("ad_account_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("import_progress", sa.Integer(), nullable=True),
        sa.Column("sync_mode", sa.String(length=16), nullable=True),
        sa.Column("sync_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("import_job_id", sa.Uuid(), nullable=True),
        sa.Column("import_cursor", sa.String(length=2048), nullable=True),
        sa.Column("last_quick_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_nightly_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_weekly_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sync_mode IS NULL OR sync_mode IN ('initial', 'quick', 'nightly', 'weekly')",
            name=op.f("ck_ad_sync_state_sync_mode"),
        ),
        sa.CheckConstraint(
            "import_cursor IS NULL OR char_length(import_cursor) <= 2048",
            name=op.f("ck_ad_sync_state_import_cursor"),
        ),
        sa.CheckConstraint(
            "import_progress IS NULL OR (import_progress BETWEEN 0 AND 100)",
            name=op.f("ck_ad_sync_state_import_progress"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ad_account_id"],
            ["ad_accounts.organization_id", "ad_accounts.id"],
            name="fk_ad_sync_state_ad_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ad_account_id", name=op.f("pk_ad_sync_state")),
    )
    op.create_table(
        "ad_campaigns",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("ad_account_id", sa.Uuid(), nullable=False),
        sa.Column("external_campaign_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("platform_type", sa.String(length=64), nullable=True),
        sa.Column("bidding_strategy_type", sa.String(length=64), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("budget_id", sa.Uuid(), nullable=True),
        sa.Column("provider_extensions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'archived', 'removed')",
            name=op.f("ck_ad_campaigns_status"),
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name=op.f("ck_ad_campaigns_dates"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ad_account_id"],
            ["ad_accounts.organization_id", "ad_accounts.id"],
            name="fk_ad_campaigns_ad_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "budget_id"],
            ["ad_budgets.organization_id", "ad_budgets.id"],
            name="fk_ad_campaigns_budget",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ad_campaigns")),
        sa.UniqueConstraint(
            "ad_account_id",
            "external_campaign_id",
            name="uq_ad_campaigns_ad_account_id_external_campaign_id",
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_ad_campaigns_organization_id_id"),
    )
    op.create_index(
        "ix_ad_campaigns_organization_id_ad_account_id",
        "ad_campaigns",
        ["organization_id", "ad_account_id"],
        unique=False,
    )
    op.create_table(
        "ad_groups",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("external_ad_group_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("platform_type", sa.String(length=64), nullable=True),
        sa.Column("budget_id", sa.Uuid(), nullable=True),
        sa.Column("provider_extensions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'archived', 'removed')",
            name=op.f("ck_ad_groups_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "budget_id"],
            ["ad_budgets.organization_id", "ad_budgets.id"],
            name="fk_ad_groups_budget",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["ad_campaigns.organization_id", "ad_campaigns.id"],
            name="fk_ad_groups_campaign",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ad_groups")),
        sa.UniqueConstraint(
            "campaign_id",
            "external_ad_group_id",
            name="uq_ad_groups_campaign_id_external_ad_group_id",
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_ad_groups_organization_id_id"),
    )
    op.create_table(
        "ads",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("ad_group_id", sa.Uuid(), nullable=False),
        sa.Column("external_ad_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("platform_type", sa.String(length=64), nullable=True),
        sa.Column("provider_extensions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'archived', 'removed')", name=op.f("ck_ads_status")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ad_group_id"],
            ["ad_groups.organization_id", "ad_groups.id"],
            name="fk_ads_ad_group",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ads")),
        sa.UniqueConstraint(
            "ad_group_id", "external_ad_id", name="uq_ads_ad_group_id_external_ad_id"
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_ads_organization_id_id"),
    )
    op.create_table(
        "ad_performance_daily",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("ad_account_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("entity_key", sa.String(length=255), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("ad_group_id", sa.Uuid(), nullable=True),
        sa.Column("ad_id", sa.Uuid(), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=True),
        sa.Column("clicks", sa.BigInteger(), nullable=True),
        sa.Column("cost", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("conversions", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("conversion_value", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "source", sa.String(length=32), server_default="platform_reported", nullable=False
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(level = 'account') = (entity_key = 'account')",
            name=op.f("ck_ad_performance_daily_entity_key"),
        ),
        sa.CheckConstraint(
            "level IN ('account', 'campaign', 'ad_group', 'ad')",
            name=op.f("ck_ad_performance_daily_level"),
        ),
        sa.CheckConstraint(
            "source IN ('platform_reported')", name=op.f("ck_ad_performance_daily_source")
        ),
        sa.CheckConstraint(
            "char_length(currency) = 3", name=op.f("ck_ad_performance_daily_currency")
        ),
        sa.CheckConstraint(
            "clicks IS NULL OR clicks >= 0", name=op.f("ck_ad_performance_daily_clicks")
        ),
        sa.CheckConstraint(
            "impressions IS NULL OR impressions >= 0",
            name=op.f("ck_ad_performance_daily_impressions"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ad_account_id"],
            ["ad_accounts.organization_id", "ad_accounts.id"],
            name="fk_ad_performance_daily_ad_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ad_group_id"],
            ["ad_groups.organization_id", "ad_groups.id"],
            name="fk_ad_performance_daily_ad_group",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ad_id"],
            ["ads.organization_id", "ads.id"],
            name="fk_ad_performance_daily_ad",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["ad_campaigns.organization_id", "ad_campaigns.id"],
            name="fk_ad_performance_daily_campaign",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ad_performance_daily")),
        sa.UniqueConstraint(
            "ad_account_id",
            "level",
            "entity_key",
            "day",
            name="uq_ad_performance_daily_ad_account_id_level_entity_key_day",
        ),
    )
    op.create_index(
        "ix_ad_performance_daily_organization_id_ad_account_id_day",
        "ad_performance_daily",
        ["organization_id", "ad_account_id", "day"],
        unique=False,
    )
    _security()


def downgrade() -> None:
    op.drop_index(
        "ix_ad_performance_daily_organization_id_ad_account_id_day",
        table_name="ad_performance_daily",
    )
    op.drop_table("ad_performance_daily")
    op.drop_table("ads")
    op.drop_table("ad_groups")
    op.drop_index("ix_ad_campaigns_organization_id_ad_account_id", table_name="ad_campaigns")
    op.drop_table("ad_campaigns")
    op.drop_table("ad_sync_state")
    op.drop_table("ad_budgets")
    op.drop_table("ad_accounts")
    op.drop_column("external_resources", "access_hint")
    op.drop_column("external_resources", "group_path")
    op.drop_column("external_resources", "unavailable_reason")
