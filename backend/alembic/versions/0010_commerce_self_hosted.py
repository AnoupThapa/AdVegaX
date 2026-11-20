"""Self-hosted commerce platforms and paged imports (Phase 2B, task 2B-02).

Additive only:

* ``stores``: ``site_url`` (normalized base URL; WordPress may live in a sub-folder),
  ``platform_version``, ``health_code`` / ``health_checked_at`` (plain-language health of a
  self-hosted store) and ``counted_statuses`` (order statuses counted in the figures, Q-2B-2).
* ``orders.excluded_reason``: kept but not counted (``status`` or ``other_currency``).
* ``commerce_sync_state``: ``import_cursor`` (the provider's opaque cursor for the next page)
  and ``import_counts`` (records applied by the running chain).

Revision ID: 0010_commerce_self_hosted
Revises: 0009_commerce_sync_modes
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_commerce_self_hosted"
down_revision: str | None = "0009_commerce_sync_modes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("stores", sa.Column("site_url", sa.String(2048), nullable=True))
    op.add_column("stores", sa.Column("platform_version", sa.String(32), nullable=True))
    op.add_column("stores", sa.Column("health_code", sa.String(64), nullable=True))
    op.add_column("stores", sa.Column("health_checked_at", TZ, nullable=True))
    op.add_column(
        "stores",
        sa.Column("counted_statuses", postgresql.ARRAY(sa.String(32)), nullable=True),
    )
    op.add_column("orders", sa.Column("excluded_reason", sa.String(32), nullable=True))
    op.create_check_constraint(
        op.f("ck_orders_excluded_reason"),
        "orders",
        "excluded_reason IS NULL OR excluded_reason IN ('status', 'other_currency')",
    )
    op.add_column("commerce_sync_state", sa.Column("import_cursor", sa.String(2048), nullable=True))
    op.add_column(
        "commerce_sync_state",
        sa.Column("import_counts", postgresql.JSONB(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_commerce_sync_state_import_cursor"),
        "commerce_sync_state",
        "import_cursor IS NULL OR char_length(import_cursor) <= 2048",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_commerce_sync_state_import_cursor"), "commerce_sync_state", type_="check"
    )
    op.drop_column("commerce_sync_state", "import_counts")
    op.drop_column("commerce_sync_state", "import_cursor")
    op.drop_constraint(op.f("ck_orders_excluded_reason"), "orders", type_="check")
    op.drop_column("orders", "excluded_reason")
    for column in (
        "counted_statuses",
        "health_checked_at",
        "health_code",
        "platform_version",
        "site_url",
    ):
        op.drop_column("stores", column)
