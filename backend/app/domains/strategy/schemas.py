"""Campaign strategy API shapes (Phase 8, task 8-05; API_SPECIFICATION §19H)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

Platform = Literal["google_ads", "meta_ads"]
Objective = Literal["sales", "leads", "awareness"]
Period = Literal["daily", "monthly"]
StrategyStatus = Literal["draft", "ready", "archived"]


class BudgetIn(BaseModel):
    """The merchant's total, in the organization's reporting currency (Q-8-5)."""

    amount: Decimal = Field(gt=0, le=Decimal(1_000_000_000), max_digits=16)
    period: Period


class StrategyCreateIn(BaseModel):
    product_id: uuid.UUID
    platforms: list[Platform] = Field(min_length=1, max_length=2)
    objective: Objective | None = None  # None: the planner proposes one
    budget: BudgetIn


class StrategyUpdateIn(BaseModel):
    """An edit: the whole strategy as edited and/or a new budget. Re-validated in full."""

    strategy: dict[str, Any] | None = None
    budget: BudgetIn | None = None


class BudgetOut(BaseModel):
    amount: Decimal
    period: Period
    currency: str


class PlatformAmountOut(BaseModel):
    amount: Decimal
    daily: Decimal


class EvidenceOut(BaseModel):
    """A figure a recommendation relies on, as AdVegaX gave it to the planner."""

    label: str
    unit: str
    value: Decimal | None
    availability: str
    reason: str | None
    currency: str | None = None


class AiRunRefOut(BaseModel):
    id: uuid.UUID
    provider: str
    model: str
    prompt_name: str
    prompt_version: str
    created_at: datetime


class StrategyOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_title: str | None
    status: StrategyStatus
    strategy: dict[str, Any]
    budget: BudgetOut
    budget_amounts: dict[str, PlatformAmountOut]
    evidence: dict[str, EvidenceOut | None]  # None: the key is not in the run's snapshot
    validated: bool  # always true: only validated strategies are stored
    ai_run: AiRunRefOut
    created_by: uuid.UUID | None
    edited_by: uuid.UUID | None
    edited_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StrategySummaryOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_title: str | None
    status: StrategyStatus
    objective: str
    platforms: list[str]
    budget: BudgetOut
    created_at: datetime
    updated_at: datetime


class UsagePeriodOut(BaseModel):
    runs: int
    succeeded: int
    rejected: int
    failed: int  # failed or timed out
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal | None  # None: no price set (or a run without one)


class UsageOut(BaseModel):
    daily_limit: int
    runs_today: int
    remaining_today: int
    today: UsagePeriodOut
    last_30_days: UsagePeriodOut
    ai_enabled: bool
