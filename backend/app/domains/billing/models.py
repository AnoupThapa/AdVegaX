"""Billing records (Phase 13, task 13-02, PHASE_13_PLAN §5; A32).

* ``billing_accounts`` — one per organization (tenant-owned, forced RLS): its Stripe customer
  and subscription, the plan and interval, Stripe's subscription status, the trial end, the
  current period end, whether it cancels at the period end, and when a payment first failed.
  The scheduler and the webhook intake read the ids with the narrow system role.
* ``billing_events`` — every Stripe webhook event received, by its id (system-owned): its type,
  when it arrived and was processed, and the result — never card details or the payload.
* ``billing_reconciliations`` — each nightly comparison with Stripe (system-owned).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey

TZ = DateTime(timezone=True)
# Stripe's subscription statuses, as AdVegaX keeps them ("none": no subscription yet).
SUBSCRIPTION_STATUSES = (
    "none",
    "trialing",
    "active",
    "past_due",
    "unpaid",
    "canceled",
    "incomplete",
    "incomplete_expired",
    "paused",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class BillingAccount(Base):
    __tablename__ = "billing_accounts"
    __table_args__ = (
        CheckConstraint(
            _in("subscription_status", SUBSCRIPTION_STATUSES), name="subscription_status"
        ),
        CheckConstraint("plan IS NULL OR plan IN ('starter', 'growth', 'scale')", name="plan"),
        CheckConstraint("interval IS NULL OR interval IN ('month', 'year')", name="interval"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    plan: Mapped[str | None] = mapped_column(String(16))
    interval: Mapped[str | None] = mapped_column(String(8))
    subscription_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="none"
    )
    trial_ends_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(TZ)
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    first_failed_at: Mapped[datetime | None] = mapped_column(TZ)
    trial_reminder_sent_at: Mapped[datetime | None] = mapped_column(TZ)
    read_only_notice_sent_at: Mapped[datetime | None] = mapped_column(TZ)
    synced_at: Mapped[datetime | None] = mapped_column(TZ)  # last read from Stripe
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class BillingEvent(Base):
    __tablename__ = "billing_events"
    __table_args__ = (
        CheckConstraint(
            "result IS NULL OR result IN ('applied', 'ignored', 'failed')", name="result"
        ),
    )

    stripe_event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column()
    received_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(TZ)
    result: Mapped[str | None] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64))


class BillingReconciliation(UUIDPrimaryKey, Base):
    __tablename__ = "billing_reconciliations"
    __table_args__ = (CheckConstraint("checked >= 0 AND fixed >= 0", name="counts"),)

    started_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    checked: Mapped[int] = mapped_column(Integer, nullable=False)
    fixed: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
