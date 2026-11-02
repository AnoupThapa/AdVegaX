"""Billing (Phase 13, task 13-02, PHASE_13_PLAN §5; A32).

* ``billing_accounts``: tenant-owned, forced RLS (read, add, change); the system role may read
  it (webhook intake and the nightly reconciliation find the organization of a Stripe
  customer or subscription).
* ``billing_events`` (read, add, change) and ``billing_reconciliations`` (read, add): system
  role only, forced RLS — the app role has no access.

Revision ID: 0024_billing
Revises: 0023_autopilot
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy
from sqlalchemy.dialects import postgresql

revision: str = "0024_billing"
down_revision: str | None = "0023_autopilot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
JSON = postgresql.JSONB(astext_type=sa.Text())
STATUSES = (
    "'none', 'trialing', 'active', 'past_due', 'unpaid', 'canceled', 'incomplete', "
    "'incomplete_expired', 'paused'"
)


def upgrade() -> None:
    op.create_table(
        "billing_accounts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(64), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(64), nullable=True),
        sa.Column("plan", sa.String(16), nullable=True),
        sa.Column("interval", sa.String(8), nullable=True),
        sa.Column("subscription_status", sa.String(24), server_default="none", nullable=False),
        sa.Column("trial_ends_at", TZ, nullable=False),
        sa.Column("current_period_end", TZ, nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("first_failed_at", TZ, nullable=True),
        sa.Column("trial_reminder_sent_at", TZ, nullable=True),
        sa.Column("read_only_notice_sent_at", TZ, nullable=True),
        sa.Column("synced_at", TZ, nullable=True),
        sa.Column("created_at", TZ, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TZ, server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            f"subscription_status IN ({STATUSES})",
            name=op.f("ck_billing_accounts_subscription_status"),
        ),
        sa.CheckConstraint(
            "plan IS NULL OR plan IN ('starter', 'growth', 'scale')",
            name=op.f("ck_billing_accounts_plan"),
        ),
        sa.CheckConstraint(
            "interval IS NULL OR interval IN ('month', 'year')",
            name=op.f("ck_billing_accounts_interval"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_billing_accounts_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_billing_accounts")),
        sa.UniqueConstraint(
            "stripe_customer_id", name=op.f("uq_billing_accounts_stripe_customer_id")
        ),
        sa.UniqueConstraint(
            "stripe_subscription_id", name=op.f("uq_billing_accounts_stripe_subscription_id")
        ),
    )
    enable_rls("billing_accounts")
    op.execute("GRANT SELECT, INSERT, UPDATE ON billing_accounts TO advegax_app")
    for command in ("SELECT", "INSERT", "UPDATE"):
        kwargs = {}
        if command in ("SELECT", "UPDATE"):
            kwargs["using"] = f"organization_id = {CURRENT_ORG}"
        if command in ("INSERT", "UPDATE"):
            kwargs["check"] = f"organization_id = {CURRENT_ORG}"
        policy(
            "billing_accounts",
            f"billing_accounts_{command.lower()}",
            command=command,
            role="advegax_app",
            **kwargs,
        )
    op.execute(
        "GRANT SELECT (organization_id, stripe_customer_id, stripe_subscription_id, "
        "subscription_status, trial_ends_at) ON billing_accounts TO advegax_system"
    )
    policy(
        "billing_accounts",
        "billing_accounts_system_select",
        command="SELECT",
        role="advegax_system",
        using="true",
    )

    op.create_table(
        "billing_events",
        sa.Column("stripe_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("received_at", TZ, nullable=False),
        sa.Column("processed_at", TZ, nullable=True),
        sa.Column("result", sa.String(16), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('applied', 'ignored', 'failed')",
            name=op.f("ck_billing_events_result"),
        ),
        sa.PrimaryKeyConstraint("stripe_event_id", name=op.f("pk_billing_events")),
    )
    op.create_table(
        "billing_reconciliations",
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("checked", sa.Integer(), nullable=False),
        sa.Column("fixed", sa.Integer(), nullable=False),
        sa.Column("details", JSON, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "checked >= 0 AND fixed >= 0", name=op.f("ck_billing_reconciliations_counts")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_reconciliations")),
    )
    grants = {
        "billing_events": ("SELECT", "INSERT", "UPDATE"),
        "billing_reconciliations": ("SELECT", "INSERT"),
    }
    for table, commands in grants.items():
        enable_rls(table)
        op.execute(f"GRANT {', '.join(commands)} ON {table} TO advegax_system")
        for command in commands:
            kwargs = {}
            if command in ("SELECT", "UPDATE"):
                kwargs["using"] = "true"
            if command in ("INSERT", "UPDATE"):
                kwargs["check"] = "true"
            policy(
                table,
                f"{table}_system_{command.lower()}",
                command=command,
                role="advegax_system",
                **kwargs,
            )


def downgrade() -> None:
    op.drop_table("billing_reconciliations")
    op.drop_table("billing_events")
    op.drop_table("billing_accounts")
