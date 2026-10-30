"""The AI platform's records (Phase 8, task 8-02, PHASE_08_PLAN §6; A26).

* ``ai_models`` and ``prompt_versions`` are **reference data**: which model and which prompt
  version a run used. Rows are added the first time a model or prompt version is used and never
  changed (the application role may read and insert, nothing else). Nothing in them belongs to
  an organization.
* ``ai_runs`` (tenant-owned, forced RLS) records every call to a model: who asked, the model and
  prompt version, the **data snapshot** sent (AdVegaX's own aggregated figures — never personal
  data or secrets), the outcome (``succeeded`` | ``rejected`` | ``failed`` | ``timed_out``), why
  an answer was rejected, tokens, estimated cost and time. A strategy (8-05) always points to the
  run it came from.
* ``campaign_strategies`` (tenant-owned, forced RLS) holds the validated strategies (8-05).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey

TZ = DateTime(timezone=True)
RUN_STATUSES = ("succeeded", "rejected", "failed", "timed_out")
RUN_TASKS = ("campaign_strategy", "creative_copy", "optimization")
STRATEGY_STATUSES = ("draft", "ready", "archived")
BUDGET_PERIODS = ("daily", "monthly")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class AiModel(UUIDPrimaryKey, Base):
    __tablename__ = "ai_models"
    __table_args__ = (
        UniqueConstraint("provider", "model_name", name="uq_ai_models_provider_model"),
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class PromptVersion(UUIDPrimaryKey, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompt_versions_name_version"),
        CheckConstraint("char_length(template_hash) = 64", name="template_hash"),
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    template_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha-256 of the text
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class AiRun(UUIDPrimaryKey, Base):
    __tablename__ = "ai_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_ai_runs_organization_id_id"),
        CheckConstraint(_in("status", RUN_STATUSES), name="status"),
        CheckConstraint(_in("task", RUN_TASKS), name="task"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens"),
        CheckConstraint("attempts BETWEEN 1 AND 5", name="attempts"),
        Index("ix_ai_runs_organization_id_created_at", "organization_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_models.id"), nullable=False)
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id"), nullable=False
    )
    task: Mapped[str] = mapped_column(String(32), nullable=False)
    # AdVegaX's own aggregated figures sent to the model (never personal data or secrets).
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # the validated answer
    # Why an answer was rejected or a call failed: plain message keys, never the model's text.
    rejection_reasons: Mapped[list[Any] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))  # USD; None = no price
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class CampaignStrategy(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "campaign_strategies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["products.organization_id", "products.id"],
            ondelete="CASCADE",
            name="fk_campaign_strategies_product",
        ),
        ForeignKeyConstraint(
            ["organization_id", "ai_run_id"],
            ["ai_runs.organization_id", "ai_runs.id"],
            name="fk_campaign_strategies_ai_run",
        ),
        UniqueConstraint("organization_id", "id", name="uq_campaign_strategies_organization_id_id"),
        CheckConstraint(_in("status", STRATEGY_STATUSES), name="status"),
        CheckConstraint(_in("budget_period", BUDGET_PERIODS), name="budget_period"),
        CheckConstraint("budget_amount > 0", name="budget_amount"),
        CheckConstraint("char_length(budget_currency) = 3", name="budget_currency"),
        Index("ix_campaign_strategies_organization_id_status", "organization_id", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ai_run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    strategy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # validated
    budget_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    budget_period: Mapped[str] = mapped_column(String(16), nullable=False)
    budget_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # The amounts AdVegaX computed from the AI's percentages (Q-8-5), per platform.
    budget_amounts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    edited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    edited_at: Mapped[datetime | None] = mapped_column(TZ)
