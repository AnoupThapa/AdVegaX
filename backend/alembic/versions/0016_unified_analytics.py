"""Unified analytics and financial engine (Phase 6, task 6-02, PHASE_06_PLAN §7; A24).

* ``fx_rates``: published exchange rates (ECB, Nepal Rastra Bank), one per source, currency
  pair and day, exactly as published. Shared reference data, **not tenant data**: the app role
  may only read it, the system role (the daily job, 6-03) reads and writes it. No RLS, because
  nothing in it belongs to an organization.
* ``ad_accounts.store_id`` and ``analytics_properties.store_id``: the store an account's spend
  or a property's visits belong to when an organization has several stores (Q-6-1). Optional,
  with a composite tenant key; removing a store only clears the reference.

The organization's reporting currency and time zone are its existing ``default_currency`` and
``default_timezone`` (Q-6-2), so no table is added for them. Additive only.

Revision ID: 0016_unified_analytics
Revises: 0015_analytics_refunds
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_unified_analytics"
down_revision: str | None = "0015_analytics_refunds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ASSIGNED = (
    ("ad_accounts", "fk_ad_accounts_store"),
    ("analytics_properties", "fk_analytics_properties_store"),
)


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("base", sa.String(length=3), nullable=False),
        sa.Column("quote", sa.String(length=3), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("unit", sa.Integer(), server_default="1", nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint("source IN ('ecb', 'nrb')", name=op.f("ck_fx_rates_source")),
        sa.CheckConstraint(
            "base ~ '^[A-Z]{3}$' AND quote ~ '^[A-Z]{3}$'", name=op.f("ck_fx_rates_currencies")
        ),
        sa.CheckConstraint("base <> quote", name=op.f("ck_fx_rates_different_currencies")),
        sa.CheckConstraint("rate > 0", name=op.f("ck_fx_rates_rate_positive")),
        sa.CheckConstraint("unit > 0", name=op.f("ck_fx_rates_unit_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_rates")),
        sa.UniqueConstraint(
            "source", "base", "quote", "rate_date", name="uq_fx_rates_source_base_quote_rate_date"
        ),
    )
    op.execute("GRANT SELECT ON fx_rates TO advegax_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON fx_rates TO advegax_system")
    for table, fk in ASSIGNED:
        op.add_column(table, sa.Column("store_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            fk,
            table,
            "stores",
            ["organization_id", "store_id"],
            ["organization_id", "id"],
            ondelete="SET NULL (store_id)",
        )


def downgrade() -> None:
    for table, fk in ASSIGNED:
        op.drop_constraint(fk, table, type_="foreignkey")
        op.drop_column(table, "store_id")
    op.drop_table("fx_rates")
