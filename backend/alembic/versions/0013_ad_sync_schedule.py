"""Ad account sync schedule (Phase 3, task 3-07, PHASE_03_PLAN §9).

The scheduler must list the imported ad accounts of every organization before any tenant
context exists, as for stores (0007). The system role gets read access to **four columns
only** — id, organization, platform and when the first import finished — never names,
figures or anything else; each account's run then works under its own tenant context.

Revision ID: 0013_ad_sync_schedule
Revises: 0012_advertising
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op
from app.db.rls_sql import policy

revision: str = "0013_ad_sync_schedule"
down_revision: str | None = "0012_advertising"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = "id, organization_id, provider, first_import_completed_at"


def upgrade() -> None:
    op.execute(f"GRANT SELECT ({COLUMNS}) ON ad_accounts TO advegax_system")
    policy(
        "ad_accounts",
        "ad_accounts_system_select",
        command="SELECT",
        role="advegax_system",
        using="true",
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS ad_accounts_system_select ON ad_accounts")
    op.execute(f"REVOKE SELECT ({COLUMNS}) ON ad_accounts FROM advegax_system")
