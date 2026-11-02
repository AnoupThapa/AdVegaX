"""Days with orders in another currency (Phase 2B, task 2B-07, Q-2B-5).

Additive only: ``financial_daily.other_currency_orders`` — how many orders in a currency other
than the store's had activity (placed or refunded) on the day. Their amounts are never added
into the figures; a day with any of them is shown as "Not available — orders in other
currencies" until currency conversion arrives (Phase 6).

Revision ID: 0011_finance_other_currency
Revises: 0010_commerce_self_hosted
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_finance_other_currency"
down_revision: str | None = "0010_commerce_self_hosted"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "financial_daily",
        sa.Column("other_currency_orders", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        op.f("ck_financial_daily_other_currency_orders"),
        "financial_daily",
        "other_currency_orders >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_financial_daily_other_currency_orders"), "financial_daily", type_="check"
    )
    op.drop_column("financial_daily", "other_currency_orders")
