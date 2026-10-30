"""Agency grants (Phase 14, task 14-01, PHASE_14_PLAN §3; A33)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey

TZ = DateTime(timezone=True)
GRANTABLE_ROLES = ("manager", "analyst", "viewer")  # never owner or admin (Q-14-2)


class AgencyGrant(UUIDPrimaryKey, Base):
    __tablename__ = "agency_grants"
    __table_args__ = (
        CheckConstraint("role IN ('manager', 'analyst', 'viewer')", name="role"),
        CheckConstraint("status IN ('pending', 'active', 'revoked')", name="status"),
        CheckConstraint("organization_id <> agency_organization_id", name="other"),
        Index(
            "uq_agency_grants_open",
            "organization_id",
            "agency_organization_id",
            unique=True,
            postgresql_where=text("status <> 'revoked'"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(  # the client
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agency_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column()
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column()
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(TZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)
