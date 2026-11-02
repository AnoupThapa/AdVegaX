"""Webhook intake log (Phase 2A, PHASE_02A_PLAN §7).

Only **metadata** is kept — never the request body — so no customer personal data that platforms
put in payloads (names, emails, addresses) is ever stored (Q8). Rows are written and read by the
system role only: a webhook arrives before AdVegaX knows which organization it belongs to.
``webhook_id`` is unique, so a redelivered webhook is recognised and ignored.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey

TZ = DateTime(timezone=True)
WEBHOOK_STATUSES = ("received", "processed", "ignored", "failed")


class WebhookEvent(UUIDPrimaryKey, Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "webhook_id", name="uq_webhook_events_provider_webhook_id"),
        CheckConstraint("status IN ('received', 'processed', 'ignored', 'failed')", name="status"),
        Index("ix_webhook_events_status_received_at", "status", "received_at"),
        Index("ix_webhook_events_received_at", "received_at"),
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    webhook_id: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    # The platform account the webhook is about (e.g. the shop domain) — never personal data.
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    object_external_id: Mapped[str | None] = mapped_column(String(255))
    object_updated_at: Mapped[datetime | None] = mapped_column(TZ)
    triggered_at: Mapped[datetime | None] = mapped_column(TZ)
    received_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    # Resolved after receipt from the account → store mapping; NULL when unknown.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="received")
    processed_at: Mapped[datetime | None] = mapped_column(TZ)
    error_code: Mapped[str | None] = mapped_column(String(64))
