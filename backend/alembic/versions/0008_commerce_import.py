"""Commerce import adjustments after verifying Shopify's schema (task 2A-06).

Verified against shopify.dev (Admin GraphQL 2026-10) on 2026-10-13:

* ``ProductStatus`` has ``UNLISTED`` → allowed product status ``unlisted``.
* A sale's action (``SaleActionType``) is ORDER, RETURN, UPDATE or UNKNOWN; the agreement that
  carries it has its own reason (``OrderActionType``: ORDER, ORDER_EDIT, REFUND, RETURN,
  UNKNOWN). ``sales_entries.action`` now uses the sale's values and the new
  ``agreement_reason`` column keeps the agreement's.
* ``SaleLineType`` has no tax line (taxes belong to each sale) but has ADDITIONAL_FEE and
  ADJUSTMENT → the line-type list follows it.
* ``sales_entries.external_line_item_id`` keeps the platform's line id so the link to the order
  line can be resolved after a bulk import, whose child rows have no guaranteed order.

``commerce_sync_state.import_job_id`` names the one import step allowed to continue, so a
duplicated job message can never start a second chain of steps.

``sales_entries`` is still empty when this runs (imports start with 2A-06).

Revision ID: 0008_commerce_import
Revises: 0007_commerce
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_commerce_import"
down_revision: str | None = "0007_commerce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_PRODUCT = "status IN ('active', 'draft', 'archived', 'deleted')"
NEW_PRODUCT = "status IN ('active', 'draft', 'archived', 'unlisted', 'deleted')"
OLD_ACTION = "action IN ('order', 'return', 'cancel', 'edit', 'other')"
NEW_ACTION = "action IN ('order', 'return', 'update', 'other')"
OLD_LINE = "line_type IN ('product', 'shipping', 'tax', 'duty', 'fee', 'tip', 'gift_card', 'other')"
NEW_LINE = (
    "line_type IN ('product', 'shipping', 'duty', 'fee', 'additional_fee', 'adjustment', "
    "'tip', 'gift_card', 'other')"
)
REASON = "agreement_reason IN ('order', 'order_edit', 'refund', 'return', 'other')"


def _unrestricted(table: str, sql: str) -> None:
    """Run a data statement over all tenants: RLS is forced on tenant tables (even for their
    owner), so it is lifted for this one statement inside the migration transaction."""
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(sql)
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    _replace_check("products", "status", NEW_PRODUCT)
    _unrestricted("sales_entries", "DELETE FROM sales_entries")  # defensive: none before 2A-06
    _replace_check("sales_entries", "action", NEW_ACTION)
    _replace_check("sales_entries", "line_type", NEW_LINE)
    op.add_column(
        "sales_entries",
        sa.Column("agreement_reason", sa.String(length=16), nullable=False, server_default="other"),
    )
    op.create_check_constraint(op.f("ck_sales_entries_agreement_reason"), "sales_entries", REASON)
    op.add_column(
        "sales_entries", sa.Column("external_line_item_id", sa.String(length=255), nullable=True)
    )
    op.add_column("commerce_sync_state", sa.Column("import_job_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("commerce_sync_state", "import_job_id")
    op.drop_column("sales_entries", "external_line_item_id")
    op.drop_constraint(op.f("ck_sales_entries_agreement_reason"), "sales_entries", type_="check")
    op.drop_column("sales_entries", "agreement_reason")
    _unrestricted("sales_entries", "DELETE FROM sales_entries")
    _replace_check("sales_entries", "line_type", OLD_LINE)
    _replace_check("sales_entries", "action", OLD_ACTION)
    _unrestricted("products", "UPDATE products SET status = 'active' WHERE status = 'unlisted'")
    _replace_check("products", "status", OLD_PRODUCT)
