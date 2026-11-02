"""Commerce sync modes (task 2A-07): the import chain also runs reconciliations.

``commerce_sync_state.sync_mode`` says what the running chain is — ``initial`` import, hourly
``reconcile`` (changes since the last run) or nightly ``deep`` check (catalogue + last 30 days
of orders) — and ``sync_started_at`` when it began, which becomes the next run's starting point.

Revision ID: 0009_commerce_sync_modes
Revises: 0008_commerce_import
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_commerce_sync_modes"
down_revision: str | None = "0008_commerce_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("commerce_sync_state", sa.Column("sync_mode", sa.String(16), nullable=True))
    op.add_column(
        "commerce_sync_state",
        sa.Column("sync_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    # RLS is forced on tenant tables (also for their owner): lift it for this one statement.
    op.execute("ALTER TABLE commerce_sync_state NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE commerce_sync_state SET sync_mode = 'initial' WHERE import_job_id IS NOT NULL"
    )
    op.execute("ALTER TABLE commerce_sync_state FORCE ROW LEVEL SECURITY")
    op.create_check_constraint(
        op.f("ck_commerce_sync_state_sync_mode"),
        "commerce_sync_state",
        "sync_mode IS NULL OR sync_mode IN ('initial', 'reconcile', 'deep')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_commerce_sync_state_sync_mode"), "commerce_sync_state", type_="check"
    )
    op.drop_column("commerce_sync_state", "sync_started_at")
    op.drop_column("commerce_sync_state", "sync_mode")
