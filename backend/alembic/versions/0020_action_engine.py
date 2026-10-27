"""Action Engine (Phase 10A, task 10A-02, PHASE_10A_PLAN §6; A28).

* ``actions`` (read, add, change), ``action_events`` (read, add — insert-only) and
  ``action_settings`` (read, add, change): tenant-owned, forced RLS; nothing is deleted by the
  application. At most one open change per campaign (partial unique index).
* The scheduler (system role) may read four columns of ``actions`` to find changes that wait
  (queued, or an unknown outcome to look up); everything else runs as the organization.
* ``external_connections`` gains who allowed changes through the connection, and when.

Revision ID: 0020_action_engine
Revises: 0019_creative_engine
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy
from sqlalchemy.dialects import postgresql

revision: str = "0020_action_engine"
down_revision: str | None = "0019_creative_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
JSON = postgresql.JSONB(astext_type=sa.Text())
STATUSES = (
    "'pending', 'approved', 'rejected', 'cancelled', 'queued', 'submitting', 'unknown', "
    "'succeeded', 'failed', 'stale'"
)
OPEN = "status IN ('pending', 'approved', 'queued', 'submitting', 'unknown')"
SYSTEM_COLUMNS = "id, organization_id, status, updated_at"


def _now() -> sa.TextClause:
    return sa.text("now()")


def _org_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
        ondelete="CASCADE",
    )


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="SET NULL"
    )


def upgrade() -> None:
    op.add_column("external_connections", sa.Column("write_access_granted_at", TZ, nullable=True))
    op.add_column(
        "external_connections", sa.Column("write_access_granted_by", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_external_connections_write_access_granted_by_users"),
        "external_connections",
        "users",
        ["write_access_granted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "actions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(48), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("ad_account_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("params", JSON, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("previous", JSON, nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("checks", JSON, nullable=False),
        sa.Column("dry_run", JSON, nullable=True),
        sa.Column("platform_request", JSON, nullable=True),
        sa.Column("platform_answer", JSON, nullable=True),
        sa.Column("observed", JSON, nullable=True),
        sa.Column("verification", sa.String(16), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("source", sa.String(16), server_default="user", nullable=False),
        sa.Column("undo_of", sa.Uuid(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", TZ, nullable=True),
        sa.Column("decision_reason", sa.String(500), nullable=True),
        sa.Column("submitted_at", TZ, nullable=True),
        sa.Column("finished_at", TZ, nullable=True),
        sa.Column("reconcile_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TZ, server_default=_now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=_now(), nullable=False),
        sa.CheckConstraint(
            "action_type IN ('campaign.pause', 'campaign.resume', 'campaign.set_daily_budget')",
            name=op.f("ck_actions_action_type"),
        ),
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f("ck_actions_status")),
        sa.CheckConstraint(
            "verification IS NULL OR verification IN ('verified', 'mismatch', 'not_checked')",
            name=op.f("ck_actions_verification"),
        ),
        sa.CheckConstraint("source IN ('user', 'recommendation')", name=op.f("ck_actions_source")),
        sa.CheckConstraint("char_length(currency) = 3", name=op.f("ck_actions_currency")),
        sa.CheckConstraint("reconcile_attempts >= 0", name=op.f("ck_actions_reconcile_attempts")),
        sa.ForeignKeyConstraint(
            ["organization_id", "ad_account_id"],
            ["ad_accounts.organization_id", "ad_accounts.id"],
            name="fk_actions_ad_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["ad_campaigns.organization_id", "ad_campaigns.id"],
            name="fk_actions_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "undo_of"],
            ["actions.organization_id", "actions.id"],
            name="fk_actions_undo_of",
        ),
        _org_fk("actions"),
        _user_fk("actions", "requested_by"),
        _user_fk("actions", "decided_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_actions")),
        sa.UniqueConstraint("organization_id", "id", name="uq_actions_organization_id_id"),
    )
    op.create_index("ix_actions_organization_id_status", "actions", ["organization_id", "status"])
    op.create_index(
        "ix_actions_organization_id_campaign_id", "actions", ["organization_id", "campaign_id"]
    )
    op.create_index(
        "ix_actions_ad_account_id_submitted_at", "actions", ["ad_account_id", "submitted_at"]
    )
    op.create_index(
        "uq_actions_one_open_per_campaign",
        "actions",
        ["campaign_id"],
        unique=True,
        postgresql_where=sa.text(OPEN),
    )
    op.create_table(
        "action_events",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("detail", JSON, nullable=False),
        sa.Column("created_at", TZ, server_default=_now(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f("ck_action_events_status")),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN ({STATUSES})",
            name=op.f("ck_action_events_from_status"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'worker')", name=op.f("ck_action_events_actor_type")
        ),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_action_events_seq")),
        sa.UniqueConstraint("action_id", "seq", name="uq_action_events_action_id_seq"),
        sa.ForeignKeyConstraint(
            ["organization_id", "action_id"],
            ["actions.organization_id", "actions.id"],
            name="fk_action_events_action",
            ondelete="CASCADE",
        ),
        _org_fk("action_events"),
        _user_fk("action_events", "actor_user_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_events")),
    )
    op.create_table(
        "action_settings",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("paused", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("require_second_person", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("max_daily_budget", sa.Numeric(20, 6), nullable=True),
        sa.Column("max_daily_budget_currency", sa.String(3), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", TZ, server_default=_now(), nullable=False),
        sa.CheckConstraint(
            "max_daily_budget IS NULL OR max_daily_budget > 0",
            name=op.f("ck_action_settings_max_daily_budget"),
        ),
        sa.CheckConstraint(
            "(max_daily_budget IS NULL) = (max_daily_budget_currency IS NULL)",
            name=op.f("ck_action_settings_max_daily_budget_currency"),
        ),
        _org_fk("action_settings"),
        _user_fk("action_settings", "updated_by"),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_action_settings")),
    )
    grants = {
        "actions": ("SELECT", "INSERT", "UPDATE"),
        "action_events": ("SELECT", "INSERT"),
        "action_settings": ("SELECT", "INSERT", "UPDATE"),
    }
    for table, commands in grants.items():
        enable_rls(table)
        op.execute(f"GRANT {', '.join(commands)} ON {table} TO advegax_app")
        for command in commands:
            kwargs = {}
            if command in ("SELECT", "UPDATE"):
                kwargs["using"] = f"organization_id = {CURRENT_ORG}"
            if command in ("INSERT", "UPDATE"):
                kwargs["check"] = f"organization_id = {CURRENT_ORG}"
            policy(
                table, f"{table}_{command.lower()}", command=command, role="advegax_app", **kwargs
            )
    op.execute(f"GRANT SELECT ({SYSTEM_COLUMNS}) ON actions TO advegax_system")
    policy(
        "actions", "actions_system_select", command="SELECT", role="advegax_system", using="true"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS actions_system_select ON actions")
    op.execute(f"REVOKE SELECT ({SYSTEM_COLUMNS}) ON actions FROM advegax_system")
    op.drop_table("action_settings")
    op.drop_table("action_events")
    op.drop_index("uq_actions_one_open_per_campaign", table_name="actions")
    op.drop_index("ix_actions_ad_account_id_submitted_at", table_name="actions")
    op.drop_index("ix_actions_organization_id_campaign_id", table_name="actions")
    op.drop_index("ix_actions_organization_id_status", table_name="actions")
    op.drop_table("actions")
    op.drop_constraint(
        op.f("fk_external_connections_write_access_granted_by_users"),
        "external_connections",
        type_="foreignkey",
    )
    op.drop_column("external_connections", "write_access_granted_by")
    op.drop_column("external_connections", "write_access_granted_at")
