"""External connections, encrypted credentials, resources and organization links (A6, A16).

Revision ID: 0005_integrations
Revises: 0004_email_outbox
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.rls_sql import CURRENT_ORG, enable_rls, policy
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "0005_integrations"
down_revision: str | None = "0004_email_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
TABLES = (
    "external_connections",
    "external_connection_credentials",
    "external_resources",
    "organization_resource_links",
)


def _tenant_policies(table: str) -> None:
    for command in ("SELECT", "INSERT", "UPDATE"):
        kwargs = {}
        if command in ("SELECT", "UPDATE"):
            kwargs["using"] = f"organization_id = {CURRENT_ORG}"
        if command in ("INSERT", "UPDATE"):
            kwargs["check"] = f"organization_id = {CURRENT_ORG}"
        policy(table, f"{table}_{command.lower()}", command=command, role="advegax_app", **kwargs)


def upgrade() -> None:
    op.create_table(
        "external_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey(
                "organizations.id",
                ondelete="CASCADE",
                name="fk_external_connections_organization_id_organizations",
            ),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("auth_scheme", sa.String(16), nullable=False),
        sa.Column(
            "authorized_by_user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_external_connections_authorized_by_user_id_users",
            ),
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("granted_scopes", ARRAY(sa.String(255)), nullable=False, server_default="{}"),
        sa.Column("external_account_label", sa.String(255)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("last_error_at", TZ),
        sa.Column("revoked_at", TZ),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_external_connections_organization_id_id"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'expired', 'revoked', 'error')",
            name="ck_external_connections_status",
        ),
        sa.CheckConstraint(
            "auth_scheme IN ('oauth2', 'api_key', 'app_key')",
            name="ck_external_connections_auth_scheme",
        ),
    )
    op.create_index(
        "ix_external_connections_organization_id_provider",
        "external_connections",
        ["organization_id", "provider"],
    )
    op.create_index(
        "ix_external_connections_authorized_by_user_id",
        "external_connections",
        ["authorized_by_user_id"],
    )

    op.create_table(
        "external_connection_credentials",
        sa.Column("connection_id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary()),
        sa.Column("wrapped_data_key", sa.LargeBinary()),
        sa.Column("key_version", sa.Integer()),
        sa.Column("token_expires_at", TZ),
        sa.Column("refresh_expires_at", TZ),
        sa.Column("last_refreshed_at", TZ),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id", "connection_id"],
            ["external_connections.organization_id", "external_connections.id"],
            ondelete="CASCADE",
            name="fk_external_connection_credentials_connection",
        ),
        sa.CheckConstraint(
            "(ciphertext IS NULL) = (wrapped_data_key IS NULL) "
            "AND (ciphertext IS NULL) = (key_version IS NULL)",
            name="ck_external_connection_credentials_secret_complete",
        ),
    )

    op.create_table(
        "external_resources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255)),
        sa.Column("currency", sa.String(3)),
        sa.Column("timezone", sa.String(64)),
        sa.Column("accessible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("capabilities", JSONB, nullable=False, server_default="{}"),
        sa.Column("discovered_at", TZ, nullable=False),
        sa.Column("last_seen_at", TZ, nullable=False),
        sa.Column("last_synced_at", TZ),
        sa.ForeignKeyConstraint(
            ["organization_id", "connection_id"],
            ["external_connections.organization_id", "external_connections.id"],
            ondelete="CASCADE",
            name="fk_external_resources_connection",
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_external_resources_organization_id_id"
        ),
        sa.UniqueConstraint(
            "connection_id",
            "kind",
            "external_id",
            name="uq_external_resources_connection_id_kind_external_id",
        ),
        sa.CheckConstraint(
            "kind IN ('store', 'ad_account', 'analytics_property', 'business_asset')",
            name="ck_external_resources_kind",
        ),
    )
    op.create_index(
        "ix_external_resources_organization_id_kind",
        "external_resources",
        ["organization_id", "kind"],
    )

    op.create_table(
        "organization_resource_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("external_resource_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "linked_by_user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_organization_resource_links_linked_by_user_id_users",
            ),
        ),
        sa.Column("linked_at", TZ, nullable=False),
        sa.Column(
            "unlinked_by_user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_organization_resource_links_unlinked_by_user_id_users",
            ),
        ),
        sa.Column("unlinked_at", TZ),
        sa.Column("unlink_reason", sa.String(32)),
        sa.ForeignKeyConstraint(
            ["organization_id", "external_resource_id"],
            ["external_resources.organization_id", "external_resources.id"],
            ondelete="CASCADE",
            name="fk_organization_resource_links_resource",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'unlinked')", name="ck_organization_resource_links_status"
        ),
        sa.CheckConstraint(
            "unlink_reason IS NULL OR unlink_reason IN "
            "('user', 'connection_revoked', 'resource_inaccessible')",
            name="ck_organization_resource_links_unlink_reason",
        ),
    )
    op.create_index(
        "uq_organization_resource_links_active",
        "organization_resource_links",
        ["external_resource_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_organization_resource_links_organization_id_status",
        "organization_resource_links",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_organization_resource_links_linked_by_user_id",
        "organization_resource_links",
        ["linked_by_user_id"],
    )
    op.create_index(
        "ix_organization_resource_links_unlinked_by_user_id",
        "organization_resource_links",
        ["unlinked_by_user_id"],
    )

    for table in TABLES:
        enable_rls(table)
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO advegax_app")
        _tenant_policies(table)

    # Key rotation is a narrow, audited system operation: re-wrap data keys only.
    op.execute("GRANT SELECT, UPDATE ON external_connection_credentials TO advegax_system")
    policy(
        "external_connection_credentials",
        "external_connection_credentials_system_select",
        command="SELECT",
        role="advegax_system",
        using="true",
    )
    policy(
        "external_connection_credentials",
        "external_connection_credentials_system_update",
        command="UPDATE",
        role="advegax_system",
        using="true",
        check="true",
    )


def downgrade() -> None:
    op.drop_table("organization_resource_links")
    op.drop_table("external_resources")
    op.drop_table("external_connection_credentials")
    op.drop_table("external_connections")
