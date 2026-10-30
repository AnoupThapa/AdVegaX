"""Autopilot API schemas (Phase 12, task 12-05; API_SPECIFICATION §19M)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Kind = Literal["spend_without_results", "losing_money"]


class AutopilotLimits(BaseModel):
    max_changes_per_day: int = Field(ge=1, le=100)
    campaign_cooldown_days: int = Field(ge=1, le=365)
    max_decrease_percent: int = Field(ge=1, le=50)
    max_cumulative_decrease_percent: int = Field(ge=1, le=90)
    cumulative_window_days: int = Field(ge=7, le=365)
    min_campaign_age_days: int = Field(ge=1, le=365)


class AutopilotPolicyIn(AutopilotLimits):
    kinds: list[Kind] = Field(max_length=2)
    ad_account_ids: list[uuid.UUID] = Field(max_length=200)
    excluded_campaign_ids: list[uuid.UUID] = Field(max_length=2000)


class AutopilotEnableIn(BaseModel):
    confirm: str = Field(max_length=200)  # the organization's name, typed


class ReadinessOut(BaseModel):
    ready: bool
    missing: list[str]  # installation_off | not_in_rollout | too_few_verified_changes | …
    verified_changes: int
    needed_changes: int


class AutopilotPolicyOut(AutopilotLimits):
    enabled: bool
    enabled_by: uuid.UUID | None
    enabled_at: datetime | None
    stopped_by: uuid.UUID | None
    stopped_at: datetime | None
    stopped_reason: str | None
    kinds: list[str]
    ad_account_ids: list[uuid.UUID]
    excluded_campaign_ids: list[uuid.UUID]
    ceilings: AutopilotLimits  # the installation's bounds: limits may only be stricter
    readiness: ReadinessOut
    updated_at: datetime | None


class AutopilotRunOut(BaseModel):
    id: uuid.UUID
    started_at: datetime
    considered: int
    made: list[uuid.UUID]
    skipped: list[dict[str, Any]]
    limit_reached: bool
    stopped_reason: str | None
