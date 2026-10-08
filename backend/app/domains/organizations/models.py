"""Organizations (tenants), memberships and invitations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey

ROLES = ("owner", "admin", "manager", "analyst", "viewer")
_ROLE_CHECK = "role IN ('owner', 'admin', 'manager', 'analyst', 'viewer')"


class Organization(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("default_currency ~ '^[A-Z]{3}$'", name="currency_iso4217"),
        CheckConstraint("status IN ('active', 'suspended')", name="status"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    default_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class Membership(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", name="uq_memberships_organization_id_user_id"
        ),
        CheckConstraint(_ROLE_CHECK, name="role"),
        CheckConstraint("status IN ('active', 'suspended', 'removed')", name="status"),
        Index("ix_memberships_user_id_status", "user_id", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")


class Invitation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint(_ROLE_CHECK, name="role"),
        CheckConstraint("status IN ('pending', 'accepted', 'revoked', 'expired')", name="status"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        Index("ix_invitations_organization_id_status", "organization_id", "status"),
        Index(
            "uq_invitations_pending_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
