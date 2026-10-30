"""Platform-neutral analytics model (Phase 5, task 5-02, PHASE_05_PLAN §8; decision Q11).

Adds analytics properties (extension of ``analytics_property`` resources), daily aggregates in
three views (total, channel, source / medium / campaign) and per-property sync state. Additive
only. Every table is tenant-owned: composite tenant keys, forced RLS and app-role policies
(DELETE included, for re-imports and erasure), as for the advertising tables (0012).

The scheduler lists imported properties before any tenant context exists, as for ad accounts
(0013): the system role reads **four columns only** of ``analytics_properties`` — id,
organization, platform and when the first import finished.

Revision ID: 0014_analytics
Revises: 0013_ad_sync_schedule
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy

revision: str = "0014_analytics"
down_revision: str | None = "0013_ad_sync_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("analytics_properties", "analytics_daily", "analytics_sync_state")
SYSTEM_COLUMNS = "id, organization_id, provider, first_import_completed_at"
MEASURES = (
    "sessions",
    "engaged_sessions",
    "total_users",
    "new_users",
    "key_events",
    "purchases",
    "purchase_revenue",
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
    op.execute(f"GRANT SELECT ({SYSTEM_COLUMNS}) ON analytics_properties TO advegax_system")
    policy(
        "analytics_properties",
        "analytics_properties_system_select",
        command="SELECT",
        role="advegax_system",
        using="true",
    )


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "analytics_properties",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("external_resource_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_property_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="importing", nullable=False),
        sa.Column("platform_status", sa.String(length=16), nullable=False),
        sa.Column("history_from", sa.Date(), nullable=True),
        sa.Column("first_import_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_code", sa.String(length=64), nullable=True),
        sa.Column("health_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "platform_status IN ('active', 'deleted')",
            name=op.f("ck_analytics_properties_platform_status"),
        ),
        sa.CheckConstraint(
            "status IN ('importing', 'active', 'disconnected', 'error')",
            name=op.f("ck_analytics_properties_status"),
        ),
        sa.CheckConstraint(
            "char_length(currency) = 3", name=op.f("ck_analytics_properties_currency")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "external_resource_id"],
            ["external_resources.organization_id", "external_resources.id"],
            name="fk_analytics_properties_external_resource",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analytics_properties")),
        sa.UniqueConstraint(
            "external_resource_id", name="uq_analytics_properties_external_resource_id"
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_analytics_properties_organization_id_id"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "external_property_id",
            name="uq_analytics_properties_org_provider_external_id",
        ),
    )
    op.create_table(
        "analytics_daily",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("breakdown", sa.String(length=16), nullable=False),
        sa.Column("dimension_key", sa.String(length=1024), nullable=False),
        sa.Column("channel_group", sa.String(length=255), nullable=True),
        sa.Column("traffic_source", sa.String(length=255), nullable=True),
        sa.Column("traffic_medium", sa.String(length=255), nullable=True),
        sa.Column("campaign", sa.String(length=255), nullable=True),
        sa.Column("sessions", sa.BigInteger(), nullable=True),
        sa.Column("engaged_sessions", sa.BigInteger(), nullable=True),
        sa.Column("total_users", sa.BigInteger(), nullable=True),
        sa.Column("new_users", sa.BigInteger(), nullable=True),
        sa.Column("key_events", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("purchases", sa.BigInteger(), nullable=True),
        sa.Column("purchase_revenue", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("other_row", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("thresholded", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("sampled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "source", sa.String(length=32), server_default="platform_reported", nullable=False
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "breakdown IN ('total', 'channel', 'source')",
            name=op.f("ck_analytics_daily_breakdown"),
        ),
        sa.CheckConstraint(
            "source IN ('platform_reported')", name=op.f("ck_analytics_daily_source")
        ),
        sa.CheckConstraint(
            "(breakdown = 'total') = (dimension_key = 'total')",
            name=op.f("ck_analytics_daily_dimension_key"),
        ),
        sa.CheckConstraint("char_length(currency) = 3", name=op.f("ck_analytics_daily_currency")),
        *(
            sa.CheckConstraint(f"{c} IS NULL OR {c} >= 0", name=op.f(f"ck_analytics_daily_{c}"))
            for c in MEASURES
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "property_id"],
            ["analytics_properties.organization_id", "analytics_properties.id"],
            name="fk_analytics_daily_property",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analytics_daily")),
        sa.UniqueConstraint(
            "property_id",
            "breakdown",
            "dimension_key",
            "day",
            name="uq_analytics_daily_property_id_breakdown_dimension_key_day",
        ),
    )
    op.create_index(
        "ix_analytics_daily_organization_id_property_id_day",
        "analytics_daily",
        ["organization_id", "property_id", "day"],
        unique=False,
    )
    op.create_table(
        "analytics_sync_state",
        sa.Column("property_id", sa.Uuid(), nullable=False),
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
            name=op.f("ck_analytics_sync_state_sync_mode"),
        ),
        sa.CheckConstraint(
            "import_cursor IS NULL OR char_length(import_cursor) <= 2048",
            name=op.f("ck_analytics_sync_state_import_cursor"),
        ),
        sa.CheckConstraint(
            "import_progress IS NULL OR (import_progress BETWEEN 0 AND 100)",
            name=op.f("ck_analytics_sync_state_import_progress"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "property_id"],
            ["analytics_properties.organization_id", "analytics_properties.id"],
            name="fk_analytics_sync_state_property",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("property_id", name=op.f("pk_analytics_sync_state")),
    )
    _security()


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS analytics_properties_system_select ON analytics_properties")
    op.execute(f"REVOKE SELECT ({SYSTEM_COLUMNS}) ON analytics_properties FROM advegax_system")
    op.drop_table("analytics_sync_state")
    op.drop_index(
        "ix_analytics_daily_organization_id_property_id_day", table_name="analytics_daily"
    )
    op.drop_table("analytics_daily")
    op.drop_table("analytics_properties")
