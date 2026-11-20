"""Indexes for foreign keys that had none starting with their columns (QA audit, QA-017).

Deleting an organization, an ad account, a product or an order cascades into these tables;
without an index each cascade reads the whole table. ``webhook_events`` is set to NULL when an
organization goes. Plain ``CREATE INDEX``: the tables are small at this stage.

Revision ID: 0028_foreign_key_indexes
Revises: 0027_platform_admin
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028_foreign_key_indexes"
down_revision: str | None = "0027_platform_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = (
    ("ix_action_events_organization_id", "action_events", ["organization_id"]),
    (
        "ix_campaign_drafts_organization_id_ad_account_id",
        "campaign_drafts",
        ["organization_id", "ad_account_id"],
    ),
    (
        "ix_campaign_strategies_organization_id_product_id",
        "campaign_strategies",
        ["organization_id", "product_id"],
    ),
    (
        "ix_recommendation_outcomes_organization_id_recommendation_id",
        "recommendation_outcomes",
        ["organization_id", "recommendation_id"],
    ),
    (
        "ix_recommendations_organization_id_ad_account_id",
        "recommendations",
        ["organization_id", "ad_account_id"],
    ),
    ("ix_sales_entries_organization_id_order_id", "sales_entries", ["organization_id", "order_id"]),
    ("ix_webhook_events_organization_id", "webhook_events", ["organization_id"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
