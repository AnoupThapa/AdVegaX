"""Global identity tables (not tenant-owned; DATABASE_SCHEMA §19)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey

USER_STATUSES = ("active", "disabled")
TOKEN_PURPOSES = ("email_verification", "password_reset", "invitation")


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("status IN ('active', 'disabled')", name="status"),
    )

    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserPasswordCredential(Timestamps, Base):
    __tablename__ = "user_password_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserSession(UUIDPrimaryKey, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("idle_expires_at <= absolute_expires_at", name="idle_within_absolute"),
        Index("ix_sessions_user_id_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    auth_method: Mapped[str] = mapped_column(String(32), nullable=False, server_default="password")
    assurance_level: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="single_factor"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent_summary: Mapped[str | None] = mapped_column(String(200))


class UserActionToken(UUIDPrimaryKey, Base):
    __tablename__ = "user_action_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('email_verification', 'password_reset', 'invitation')", name="purpose"
        ),
        Index("ix_user_action_tokens_user_id_purpose", "user_id", "purpose"),
    )

    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    email: Mapped[str | None] = mapped_column(String(254))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invitations.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
