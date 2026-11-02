"""The optimization engine's records (Phase 11, task 11-02, PHASE_11_PLAN §5; A30).

* ``recommendations`` — one piece of advice about one campaign (or the business, for a funnel
  drop-off): what AdVegaX noticed with its figures, what it proposes (a Phase 10A change with
  exact values, or nothing: "look into it"), the explanation, confidence, assumptions and risks
  (by the AI or by AdVegaX's own rules), until when it is valid, and the decision. At most one
  **open** recommendation per campaign and kind (``fingerprint``). An approved recommendation
  becomes an Action Engine change (``actions.recommendation_id``).
* ``recommendation_outcomes`` — what happened to the campaign 7 and 14 days after the change:
  its figures before and after (never a claim that the change caused it).
* ``optimization_settings`` — the organization's thresholds, the day of the last daily look and
  the "Look again now" uses of the day.

All tenant-owned with forced row-level security; nothing is deleted by the application.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
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
KINDS = ("spend_without_results", "losing_money", "budget_limited", "cost_jump", "funnel_drop")
STATUSES = ("open", "approved", "rejected", "done", "expired", "out_of_date", "superseded")
CONFIDENCES = ("low", "medium", "high")
EXPLAINED_BY = ("ai", "rules")
REJECT_REASONS = ("not_relevant", "figures_wrong", "wrong_time", "other")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _user() -> Any:
    return ForeignKey("users.id", ondelete="SET NULL")


class Recommendation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_recommendations_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["ad_campaigns.organization_id", "ad_campaigns.id"],
            ondelete="CASCADE",
            name="fk_recommendations_campaign",
        ),
        ForeignKeyConstraint(
            ["organization_id", "ad_account_id"],
            ["ad_accounts.organization_id", "ad_accounts.id"],
            ondelete="CASCADE",
            name="fk_recommendations_ad_account",
        ),
        ForeignKeyConstraint(
            ["organization_id", "ai_run_id"],
            ["ai_runs.organization_id", "ai_runs.id"],
            name="fk_recommendations_ai_run",
        ),
        CheckConstraint(_in("kind", KINDS), name="kind"),
        CheckConstraint(_in("status", STATUSES), name="status"),
        CheckConstraint(_in("confidence", CONFIDENCES), name="confidence"),
        CheckConstraint(_in("explained_by", EXPLAINED_BY), name="explained_by"),
        CheckConstraint(
            "decision_reason IS NULL OR " + _in("decision_reason", REJECT_REASONS),
            name="decision_reason",
        ),
        CheckConstraint("rank >= 1", name="rank"),
        CheckConstraint("campaign_id IS NOT NULL OR kind = 'funnel_drop'", name="campaign"),
        Index("ix_recommendations_organization_id_status", "organization_id", "status"),
        Index("ix_recommendations_organization_id_campaign_id", "organization_id", "campaign_id"),
        Index(
            "uq_recommendations_one_open",
            "organization_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column()
    ad_account_id: Mapped[uuid.UUID | None] = mapped_column()
    # The figures and periods behind it, as AdVegaX computed them (the source of truth).
    signal: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # {"action_type": ..., "params": {...}} in the account currency, or {} ("look into it").
    proposal: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # The 10A checks run on AdVegaX's own copy of the campaign when the advice was made.
    prechecks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # The campaign's status and budget when it was made (approval compares them).
    campaign_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[str] = mapped_column(String(1200), nullable=False)
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    risks: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    explained_by: Mapped[str] = mapped_column(String(8), nullable=False)
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    expires_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    # Campaign (or funnel step) and kind: one open recommendation each.
    fingerprint: Mapped[str] = mapped_column(String(200), nullable=False)
    # Why it closed without a decision (out of date: campaign_changed | no_longer_true).
    closed_reason: Mapped[str | None] = mapped_column(String(64))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    decided_at: Mapped[datetime | None] = mapped_column(TZ)
    decision_reason: Mapped[str | None] = mapped_column(String(32))
    decision_note: Mapped[str | None] = mapped_column(String(500))


class RecommendationOutcome(UUIDPrimaryKey, Base):
    __tablename__ = "recommendation_outcomes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "recommendation_id"],
            ["recommendations.organization_id", "recommendations.id"],
            ondelete="CASCADE",
            name="fk_recommendation_outcomes_recommendation",
        ),
        CheckConstraint("after_days IN (7, 14)", name="after_days"),
        UniqueConstraint(
            "recommendation_id", "after_days", name="uq_recommendation_outcomes_after"
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    recommendation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    after_days: Mapped[int] = mapped_column(Integer, nullable=False)
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class OptimizationSettings(Base):
    __tablename__ = "optimization_settings"
    __table_args__ = (
        CheckConstraint("min_spend > 0", name="min_spend"),
        CheckConstraint("min_conversions >= 1", name="min_conversions"),
        CheckConstraint("budget_step_percent BETWEEN 5 AND 50", name="budget_step_percent"),
        CheckConstraint("cost_jump_percent BETWEEN 10 AND 200", name="cost_jump_percent"),
        CheckConstraint("refreshes_used >= 0", name="refreshes_used"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    # In the organization's reporting currency (Q-11-3).
    min_spend: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    min_conversions: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_step_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_jump_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    last_run_on: Mapped[date | None] = mapped_column(Date)  # the reporting time zone's day
    refreshes_on: Mapped[date | None] = mapped_column(Date)
    refreshes_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # What the last look found: when, how many campaigns, whether the profit rules could be
    # used (and why not), and who explained the advice (the AI or AdVegaX's own text).
    last_run_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_user())
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
