"""The Action Engine's records (Phase 10A, task 10A-02, PHASE_10A_PLAN §6; A28).

* ``actions`` — one requested change to one campaign, from request to verification. Its
  ``status`` moves only forward (``engine.TRANSITIONS``); at most one **open** change per
  campaign (a partial unique index), so two changes never race and a repeated request is a
  duplicate.
* ``action_events`` — every status change, who or what made it and why (insert-only).
* ``action_settings`` — the organization's "Pause all changes", the second-person rule and the
  maximum daily budget per campaign.

All tenant-owned with forced row-level security; nothing is deleted by the application. The
scheduler reads four columns of ``actions`` with the system role to find work that waits.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey

TZ = DateTime(timezone=True)
ACTION_TYPES = (
    "campaign.pause",
    "campaign.resume",
    "campaign.set_daily_budget",
    # Phase 10B: from a campaign draft (``draft_id``); there is no campaign row yet.
    "campaign.create",
    "campaign.go_live",
    "campaign.remove_draft_objects",
)
DRAFT_ACTIONS = ("campaign.create", "campaign.go_live", "campaign.remove_draft_objects")
ACTION_STATUSES = (
    "pending",
    "approved",
    "rejected",
    "cancelled",
    "queued",
    "submitting",
    "unknown",
    "succeeded",
    "failed",
    "stale",
)
# Waiting for a decision or on its way to the platform: at most one per campaign.
OPEN_STATUSES = ("pending", "approved", "queued", "submitting", "unknown")
VERIFICATIONS = ("verified", "mismatch", "not_checked")
SOURCES = ("user", "recommendation")
EVENT_ACTORS = ("user", "worker")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _user() -> Any:
    return ForeignKey("users.id", ondelete="SET NULL")


class Action(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "actions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_actions_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "ad_account_id"],
            ["ad_accounts.organization_id", "ad_accounts.id"],
            ondelete="CASCADE",
            name="fk_actions_ad_account",
        ),
        ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["ad_campaigns.organization_id", "ad_campaigns.id"],
            ondelete="CASCADE",
            name="fk_actions_campaign",
        ),
        ForeignKeyConstraint(
            ["organization_id", "draft_id"],
            ["campaign_drafts.organization_id", "campaign_drafts.id"],
            ondelete="CASCADE",
            name="fk_actions_draft",
        ),
        CheckConstraint(
            "(draft_id IS NULL) <> (" + _in("action_type", DRAFT_ACTIONS) + ")",
            name="draft_actions",
        ),
        CheckConstraint(
            "campaign_id IS NOT NULL OR " + _in("action_type", DRAFT_ACTIONS), name="campaign"
        ),
        Index(
            "uq_actions_one_open_per_draft",
            "draft_id",
            unique=True,
            postgresql_where=text(_in("status", OPEN_STATUSES)),
        ),
        ForeignKeyConstraint(
            ["organization_id", "recommendation_id"],
            ["recommendations.organization_id", "recommendations.id"],
            name="fk_actions_recommendation",
        ),
        CheckConstraint(
            "(recommendation_id IS NULL) = (source = 'user')", name="recommendation_source"
        ),
        ForeignKeyConstraint(
            ["organization_id", "undo_of"],
            ["actions.organization_id", "actions.id"],
            name="fk_actions_undo_of",
        ),
        CheckConstraint(_in("action_type", ACTION_TYPES), name="action_type"),
        CheckConstraint(_in("status", ACTION_STATUSES), name="status"),
        CheckConstraint(
            "verification IS NULL OR " + _in("verification", VERIFICATIONS), name="verification"
        ),
        CheckConstraint(_in("source", SOURCES), name="source"),
        CheckConstraint("char_length(currency) = 3", name="currency"),
        CheckConstraint("reconcile_attempts >= 0", name="reconcile_attempts"),
        Index("ix_actions_organization_id_status", "organization_id", "status"),
        Index("ix_actions_organization_id_campaign_id", "organization_id", "campaign_id"),
        Index("ix_actions_ad_account_id_submitted_at", "ad_account_id", "submitted_at"),
        Index("ix_actions_recommendation_id", "recommendation_id"),
        Index(
            "uq_actions_one_open_per_campaign",
            "campaign_id",
            unique=True,
            postgresql_where=text(_in("status", OPEN_STATUSES)),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # The campaign changed (10A); null for a draft's actions (10B) — see ``draft_id``.
    campaign_id: Mapped[uuid.UUID | None] = mapped_column()
    draft_id: Mapped[uuid.UUID | None] = mapped_column()
    # The values of the change, e.g. {"daily_budget": "60.00"} in the account currency.
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # The campaign as the platform reported it when the change was requested.
    previous: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    # Identifies the change (campaign, type, values): an identical open request is a duplicate.
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    dry_run: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Exactly what was sent (platform method and fields, never a token) and the answer.
    platform_request: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    platform_answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # The campaign read back after the change (or while looking up an unknown outcome).
    observed: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    verification: Mapped[str | None] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="user")
    undo_of: Mapped[uuid.UUID | None] = mapped_column()
    # Phase 11: the recommendation this change was made from (``source = recommendation``).
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column()
    requested_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    decided_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    decided_at: Mapped[datetime | None] = mapped_column(TZ)
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    submitted_at: Mapped[datetime | None] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    reconcile_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class ActionEvent(UUIDPrimaryKey, Base):
    __tablename__ = "action_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "action_id"],
            ["actions.organization_id", "actions.id"],
            ondelete="CASCADE",
            name="fk_action_events_action",
        ),
        CheckConstraint(_in("status", ACTION_STATUSES), name="status"),
        CheckConstraint(
            "from_status IS NULL OR " + _in("from_status", ACTION_STATUSES), name="from_status"
        ),
        CheckConstraint(_in("actor_type", EVENT_ACTORS), name="actor_type"),
        CheckConstraint("seq >= 1", name="seq"),
        UniqueConstraint("action_id", "seq", name="uq_action_events_action_id_seq"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    action_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, … in order of the steps
    from_status: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(_user())
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class ActionSettings(Base):
    __tablename__ = "action_settings"
    __table_args__ = (
        CheckConstraint(
            "max_daily_budget IS NULL OR max_daily_budget > 0", name="max_daily_budget"
        ),
        CheckConstraint(
            "(max_daily_budget IS NULL) = (max_daily_budget_currency IS NULL)",
            name="max_daily_budget_currency",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    require_second_person: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # The most a campaign may spend a day, in the organization's reporting currency.
    max_daily_budget: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    max_daily_budget_currency: Mapped[str | None] = mapped_column(String(3))
    # Phase 10B: the store's own web addresses landing pages may use, besides the platform
    # domain (e.g. a Shopify store's custom domain), chosen by owners and admins.
    landing_domains: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
