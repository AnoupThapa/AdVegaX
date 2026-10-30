"""Controlled autopilot's records (Phase 12, task 12-02, PHASE_12_PLAN §5; A31).

* ``autopilot_policies`` — one per organization: whether autopilot is on, who switched it on or
  off (or why it stopped itself), which kinds of advice it may act on (only spend-reducing
  ones), which ad accounts are included and which campaigns excluded, and its limits.
* ``autopilot_runs`` — each time autopilot looked at new advice: what it considered, the changes
  it made and what it skipped, with the reason.

Both tenant-owned with forced row-level security; nothing is deleted by the application.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey

TZ = DateTime(timezone=True)
# Only advice whose change lowers spend (Q-12-1): pause, and a lower daily budget.
AUTOMATIC_KINDS = ("spend_without_results", "losing_money")


def _user() -> Any:
    return ForeignKey("users.id", ondelete="SET NULL")


class AutopilotPolicy(Base):
    __tablename__ = "autopilot_policies"
    __table_args__ = (
        CheckConstraint("max_changes_per_day >= 1", name="max_changes_per_day"),
        CheckConstraint("campaign_cooldown_days >= 1", name="campaign_cooldown_days"),
        CheckConstraint("max_decrease_percent BETWEEN 1 AND 50", name="max_decrease_percent"),
        CheckConstraint(
            "max_cumulative_decrease_percent BETWEEN 1 AND 90",
            name="max_cumulative_decrease_percent",
        ),
        CheckConstraint("cumulative_window_days >= 7", name="cumulative_window_days"),
        CheckConstraint("min_campaign_age_days >= 1", name="min_campaign_age_days"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    enabled_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    enabled_at: Mapped[datetime | None] = mapped_column(TZ)
    stopped_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    stopped_at: Mapped[datetime | None] = mapped_column(TZ)
    # Why it is off: stopped (by a person) or what made it stop itself.
    stopped_reason: Mapped[str | None] = mapped_column(String(64))
    kinds: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    ad_account_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    excluded_campaign_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    max_changes_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    campaign_cooldown_days: Mapped[int] = mapped_column(Integer, nullable=False)
    max_decrease_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    max_cumulative_decrease_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    cumulative_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    min_campaign_age_days: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class AutopilotRun(UUIDPrimaryKey, Base):
    __tablename__ = "autopilot_runs"
    __table_args__ = (
        CheckConstraint("considered >= 0", name="considered"),
        Index("ix_autopilot_runs_organization_id_started_at", "organization_id", "started_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    considered: Mapped[int] = mapped_column(Integer, nullable=False)
    made: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # action ids
    skipped: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    limit_reached: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    stopped_reason: Mapped[str | None] = mapped_column(String(64))
