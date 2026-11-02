"""Funnel intelligence (Phase 7, task 7-02, PHASE_07_PLAN §7; A25).

* ``analytics_daily``: product views (``view_item`` events), adds to cart and checkouts started
  — the funnel's middle, from Google Analytics (Q-7-3) — and a fourth view, ``landing_page``,
  with the page a session started on (a path, never a query string). Nullable: unknown until
  read.
* ``ad_performance_daily``: Meta's own funnel actions — landing page views, content views, adds
  to cart, checkouts initiated (Q-7-4). Nullable: unknown until read; Google Ads never has them.
* ``analytics_properties.funnel_reread_at`` / ``ad_accounts.funnel_reread_at``: when a source
  was read again once for these figures; a property or account imported before Phase 7 is
  re-read once in the background (sync mode ``reread``).

No new tables; forced RLS unchanged. Additive only.

Revision ID: 0017_funnel
Revises: 0016_unified_analytics
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_funnel"
down_revision: str | None = "0016_unified_analytics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYTICS_COUNTS = ("item_view_events", "add_to_carts", "checkouts")
AD_ACTIONS = ("landing_page_views", "content_views", "adds_to_cart", "checkouts_initiated")
OLD_MODES = "sync_mode IS NULL OR sync_mode IN ('initial', 'quick', 'nightly', 'weekly')"
NEW_MODES = "sync_mode IS NULL OR sync_mode IN ('initial', 'quick', 'nightly', 'weekly', 'reread')"
OLD_BREAKDOWNS = "breakdown IN ('total', 'channel', 'source')"
NEW_BREAKDOWNS = "breakdown IN ('total', 'channel', 'source', 'landing_page')"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    for column in ANALYTICS_COUNTS:
        op.add_column("analytics_daily", sa.Column(column, sa.BigInteger(), nullable=True))
        op.create_check_constraint(
            op.f(f"ck_analytics_daily_{column}"),
            "analytics_daily",
            f"{column} IS NULL OR {column} >= 0",
        )
    op.add_column("analytics_daily", sa.Column("landing_page", sa.String(1024), nullable=True))
    _replace_check("analytics_daily", "breakdown", NEW_BREAKDOWNS)
    for column in AD_ACTIONS:
        op.add_column(
            "ad_performance_daily",
            sa.Column(column, sa.Numeric(precision=20, scale=6), nullable=True),
        )
        op.create_check_constraint(
            op.f(f"ck_ad_performance_daily_{column}"),
            "ad_performance_daily",
            f"{column} IS NULL OR {column} >= 0",
        )
    for table in ("analytics_properties", "ad_accounts"):
        op.add_column(table, sa.Column("funnel_reread_at", sa.DateTime(timezone=True)))
    _replace_check("analytics_sync_state", "sync_mode", NEW_MODES)
    _replace_check("ad_sync_state", "sync_mode", NEW_MODES)


def downgrade() -> None:
    op.execute("DELETE FROM analytics_daily WHERE breakdown = 'landing_page'")
    op.execute("UPDATE analytics_sync_state SET sync_mode = NULL WHERE sync_mode = 'reread'")
    op.execute("UPDATE ad_sync_state SET sync_mode = NULL WHERE sync_mode = 'reread'")
    _replace_check("ad_sync_state", "sync_mode", OLD_MODES)
    _replace_check("analytics_sync_state", "sync_mode", OLD_MODES)
    for table in ("ad_accounts", "analytics_properties"):
        op.drop_column(table, "funnel_reread_at")
    for column in AD_ACTIONS:
        op.drop_column("ad_performance_daily", column)
    _replace_check("analytics_daily", "breakdown", OLD_BREAKDOWNS)
    op.drop_column("analytics_daily", "landing_page")
    for column in ANALYTICS_COUNTS:
        op.drop_column("analytics_daily", column)
