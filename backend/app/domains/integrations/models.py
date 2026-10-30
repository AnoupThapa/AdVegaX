"""External connections, encrypted credentials, discovered resources and organization links (A6).

Every table is tenant-owned. Composite foreign keys ``(organization_id, parent_id)`` make
cross-tenant references impossible even if application code is wrong.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey

CONNECTION_STATUSES = ("active", "expired", "revoked", "error")
RESOURCE_KINDS = ("store", "ad_account", "analytics_property", "business_asset")


class ExternalConnection(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "external_connections"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "id", name="uq_external_connections_organization_id_id"
        ),
        CheckConstraint("status IN ('active', 'expired', 'revoked', 'error')", name="status"),
        CheckConstraint("auth_scheme IN ('oauth2', 'api_key', 'app_key')", name="auth_scheme"),
        Index("ix_external_connections_organization_id_provider", "organization_id", "provider"),
        # One live connection per platform account across ALL organizations (Q6, Phase 2A): a
        # second connection would retire the first one's token on platforms such as Shopify.
        Index(
            "uq_external_connections_live_account",
            "provider",
            "external_account_id",
            unique=True,
            postgresql_where=text("external_account_id IS NOT NULL AND status <> 'revoked'"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    auth_scheme: Mapped[str] = mapped_column(String(16), nullable=False)
    authorized_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    granted_scopes: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)), nullable=False, server_default="{}"
    )
    external_account_label: Mapped[str | None] = mapped_column(String(255))
    # Stable platform account identifier (e.g. a Shopify shop domain). NULL for providers
    # that connect to many accounts at once.
    external_account_id: Mapped[str | None] = mapped_column(String(255))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "Allow changes" (Phase 10A, Q-10A-2): who allowed the Action Engine to change ad
    # accounts through this connection, and when. NULL = read-only (the default).
    write_access_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    write_access_granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class ExternalConnectionCredential(Timestamps, Base):
    __tablename__ = "external_connection_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "connection_id"],
            ["external_connections.organization_id", "external_connections.id"],
            ondelete="CASCADE",
            name="fk_external_connection_credentials_connection",
        ),
        CheckConstraint(
            "(ciphertext IS NULL) = (wrapped_data_key IS NULL) "
            "AND (ciphertext IS NULL) = (key_version IS NULL)",
            name="secret_complete",
        ),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    wrapped_data_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_version: Mapped[int | None] = mapped_column(Integer)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExternalResource(UUIDPrimaryKey, Base):
    __tablename__ = "external_resources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "connection_id"],
            ["external_connections.organization_id", "external_connections.id"],
            ondelete="CASCADE",
            name="fk_external_resources_connection",
        ),
        UniqueConstraint("organization_id", "id", name="uq_external_resources_organization_id_id"),
        UniqueConstraint(
            "connection_id",
            "kind",
            "external_id",
            name="uq_external_resources_connection_id_kind_external_id",
        ),
        CheckConstraint(
            "kind IN ('store', 'ad_account', 'analytics_property', 'business_asset')", name="kind"
        ),
        Index("ix_external_resources_organization_id_kind", "organization_id", "kind"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str | None] = mapped_column(String(3))
    timezone: Mapped[str | None] = mapped_column(String(64))
    accessible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Phase 3 (0012): why an account cannot be linked (plain message key such as
    # ``account_cancelled`` or ``manager_account``), the groups it sits in for display (e.g. the
    # Google Ads manager accounts above it) and an opaque provider value needed to reach it
    # (Google Ads: the manager account to sign in through). None of these is a secret.
    unavailable_reason: Mapped[str | None] = mapped_column(String(64))
    group_path: Mapped[str | None] = mapped_column(String(1024))
    access_hint: Mapped[str | None] = mapped_column(String(255))
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrganizationResourceLink(UUIDPrimaryKey, Base):
    __tablename__ = "organization_resource_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "external_resource_id"],
            ["external_resources.organization_id", "external_resources.id"],
            ondelete="CASCADE",
            name="fk_organization_resource_links_resource",
        ),
        CheckConstraint("status IN ('active', 'unlinked')", name="status"),
        CheckConstraint(
            "unlink_reason IS NULL OR unlink_reason IN "
            "('user', 'connection_revoked', 'resource_inaccessible')",
            name="unlink_reason",
        ),
        Index(
            "uq_organization_resource_links_active",
            "external_resource_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_organization_resource_links_organization_id_status", "organization_id", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    linked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unlinked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unlink_reason: Mapped[str | None] = mapped_column(String(32))
