"""Data retention (Phase 15, task 15-01, PHASE_15_PLAN Q-15-3; A34).

* The system role may read which resources are linked (``organization_resource_links``:
  organization, resource, status, when unlinked) to find data past its retention.
* The **system** role may delete ``external_resources`` (the retention job only). The
  database's own cascades then remove that resource's store, ad account or analytics property
  and everything imported for it. The app role still cannot delete integration rows (1B rule).

Revision ID: 0026_retention
Revises: 0025_agency
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op
from app.db.rls_sql import policy

revision: str = "0026_retention"
down_revision: str | None = "0025_agency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LINK_COLUMNS = "organization_id, external_resource_id, status, unlinked_at"


def upgrade() -> None:
    op.execute(f"GRANT SELECT ({LINK_COLUMNS}) ON organization_resource_links TO advegax_system")
    policy(
        "organization_resource_links",
        "organization_resource_links_system_select",
        command="SELECT",
        role="advegax_system",
        using="true",
    )
    op.execute("GRANT SELECT (id), DELETE ON external_resources TO advegax_system")
    policy(
        "external_resources",
        "external_resources_system_delete",
        command="DELETE",
        role="advegax_system",
        using="true",
    )
    policy(
        "external_resources",
        "external_resources_system_select",
        command="SELECT",
        role="advegax_system",
        using="true",
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS external_resources_system_select ON external_resources")
    op.execute("DROP POLICY IF EXISTS external_resources_system_delete ON external_resources")
    op.execute("REVOKE SELECT (id), DELETE ON external_resources FROM advegax_system")
    op.execute(
        "DROP POLICY IF EXISTS organization_resource_links_system_select "
        "ON organization_resource_links"
    )
    op.execute(f"REVOKE SELECT ({LINK_COLUMNS}) ON organization_resource_links FROM advegax_system")
