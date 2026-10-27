"""Recommendations API schemas (Phase 11, task 11-06; API_SPECIFICATION §19L)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domains.actions.schemas import ActionCheckOut

Kind = Literal[
    "spend_without_results", "losing_money", "budget_limited", "cost_jump", "funnel_drop"
]
Status = Literal["open", "approved", "rejected", "done", "expired", "out_of_date", "superseded"]
RejectReason = Literal["not_relevant", "figures_wrong", "wrong_time", "other"]


class CampaignRef(BaseModel):
    id: uuid.UUID
    name: str
    provider: str
    ad_account_id: uuid.UUID
    ad_account_name: str | None


class ProposalOut(BaseModel):
    """The change AdVegaX proposes, or none ("look into it")."""

    action_type: Literal["campaign.pause", "campaign.set_daily_budget"] | None
    params: dict[str, str]
    currency: str | None
    previous_daily_budget: str | None
    text: str  # e.g. "Lower the daily budget from AUD 50.00 to AUD 40.00"


class ActionRefOut(BaseModel):
    id: uuid.UUID
    status: str
    verification: str | None


class OutcomeOut(BaseModel):
    after_days: int
    before: dict[str, Any]
    after: dict[str, Any]
    created_at: datetime


class RecommendationOut(BaseModel):
    id: uuid.UUID
    kind: Kind
    status: Status
    campaign: CampaignRef | None
    funnel: dict[str, Any] | None  # the funnel step, for a drop-off
    figures: dict[str, str]  # written out, in the reporting currency
    raw_figures: dict[str, Any]  # as computed (strings; None = not available)
    periods: dict[str, str]
    currency: str
    proposal: ProposalOut
    note: str | None  # why no change is proposed (e.g. budget_shared)
    prechecks: list[ActionCheckOut]
    ready: bool  # every pre-check passed (a change can be requested)
    explanation: str
    confidence: Literal["low", "medium", "high"]
    assumptions: list[str]
    risks: list[str]
    rank: int
    explained_by: Literal["ai", "rules"]
    ai_run_id: uuid.UUID | None
    expires_at: datetime
    closed_reason: str | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: RejectReason | None
    decision_note: str | None
    action: ActionRefOut | None
    outcomes: list[OutcomeOut]
    created_at: datetime


class SummaryOut(BaseModel):
    enabled: bool
    open: int
    last_run: dict[str, Any] | None
    refreshes_left: int


class RecommendationListOut(BaseModel):
    summary: SummaryOut
    items: list[RecommendationOut]


class RejectIn(BaseModel):
    reason: RejectReason
    note: str | None = Field(default=None, max_length=500)


class OptimizationSettingsIn(BaseModel):
    min_spend: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    min_conversions: int = Field(ge=1, le=1000)
    budget_step_percent: int = Field(ge=5, le=50)
    cost_jump_percent: int = Field(ge=10, le=200)


class OptimizationSettingsOut(BaseModel):
    enabled: bool
    currency: str
    min_spend: str
    min_conversions: int
    budget_step_percent: int
    cost_jump_percent: int
    max_step_percent: int  # the Action Engine's own limit
    updated_at: datetime | None
