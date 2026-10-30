"""Google Analytics revenue can be negative (Phase 5, task 5-05).

GA4's ``purchaseRevenue`` is purchases **minus refunds**, so a day with more refunded than new
revenue is negative. 0014 refused negative revenue; this drops that one check so the figure is
stored exactly as reported (A10: never altered or hidden). Every other measure stays >= 0.

Downgrade restores the check; it fails while negative rows exist (delete them first).

Revision ID: 0015_analytics_refunds
Revises: 0014_analytics
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_analytics_refunds"
down_revision: str | None = "0014_analytics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_analytics_daily_purchase_revenue"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), "analytics_daily", type_="check")


def downgrade() -> None:
    op.create_check_constraint(
        op.f(CHECK), "analytics_daily", "purchase_revenue IS NULL OR purchase_revenue >= 0"
    )
