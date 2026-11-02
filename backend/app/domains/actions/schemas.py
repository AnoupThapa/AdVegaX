"""Action Engine API schemas (Phase 10A, task 10A-05; API_SPECIFICATION §19J)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

ActionType = Literal["campaign.pause", "campaign.resume", "campaign.set_daily_budget"]
AnyActionType = Literal[
    "campaign.pause",
    "campaign.resume",
    "campaign.set_daily_budget",
    "campaign.create",
    "campaign.go_live",
    "campaign.remove_draft_objects",
]
ActionStatus = Literal[
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
]


class ActionIn(BaseModel):
    """One change to one campaign. ``params`` for a daily budget: ``{"daily_budget": "60.00"}``
    in the ad account's currency; nothing for pause and resume."""

    action_type: ActionType
    campaign_id: uuid.UUID
    params: dict[str, str] = Field(default_factory=dict, max_length=4)


class ActionCheckOut(BaseModel):
    check: str  # shape | resource | budget | limits | state
    result: str  # passed | failed | skipped
    reason: str | None


class DryRunOut(BaseModel):
    """The platform's own check of the change, without making it."""

    result: str  # passed | failed | skipped
    reason: str | None = None


class CampaignStateOut(BaseModel):
    """A campaign as the platform reported it."""

    status: str | None
    budget_level: str | None  # campaign | ad_group (Meta ad sets) | null
    budget_period: str | None  # daily | lifetime | null
    daily_budget: str | None  # in the account currency's minor units
    budget_shared: bool


class BudgetLimitsOut(BaseModel):
    """The daily budget this campaign may be given in one change (computed by AdVegaX)."""

    lowest: str | None
    highest: str | None
    platform_minimum: str | None
    organization_maximum: str | None
    increase_percent: int
    decrease_percent: int


class ActionPreviewOut(BaseModel):
    action_type: ActionType
    campaign_id: uuid.UUID
    currency: str
    currency_minor_units: int
    passed: bool
    checks: list[ActionCheckOut]
    dry_run: DryRunOut
    current: CampaignStateOut | None
    budget_limits: BudgetLimitsOut | None


class CampaignRefOut(BaseModel):
    id: uuid.UUID
    name: str
    external_id: str
    ad_account_id: uuid.UUID
    ad_account_name: str | None


class DraftRefOut(BaseModel):
    """A campaign draft's change (Phase 10B): the campaign it creates or switches on."""

    id: uuid.UUID
    name: str
    platform: str
    ad_account_id: uuid.UUID
    ad_account_name: str | None
    strategy_id: uuid.UUID
    status: str


class ActionEventOut(BaseModel):
    from_status: str | None
    status: str
    actor_type: str
    actor_user_id: uuid.UUID | None
    detail: dict[str, Any]
    created_at: datetime


class ActionOut(BaseModel):
    id: uuid.UUID
    action_type: AnyActionType
    provider: str
    campaign: CampaignRefOut | None  # null for a draft's change (Phase 10B): see ``draft``
    draft: DraftRefOut | None = None
    currency: str
    currency_minor_units: int
    params: dict[str, str]
    previous: CampaignStateOut
    observed: CampaignStateOut | None
    status: ActionStatus
    checks: list[ActionCheckOut]
    dry_run: DryRunOut | None
    verification: str | None  # verified | mismatch | not_checked
    error_code: str | None
    # Exactly what was sent to the platform (method and fields, never a token).
    platform_request: dict[str, Any] | None
    platform_answer: dict[str, Any] | None
    source: str
    recommendation_id: uuid.UUID | None = None  # Phase 11: made from this advice
    undo_of: uuid.UUID | None
    requested_by: uuid.UUID | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    submitted_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    can_undo: bool
    events: list[ActionEventOut] = Field(default_factory=list)


class ActionRejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ActionSettingsIn(BaseModel):
    paused: bool
    require_second_person: bool
    # The most a campaign may spend a day, in the organization's reporting currency; null =
    # not chosen (budget changes are refused until it is).
    max_daily_budget: Decimal | None = Field(default=None, gt=0, lt=Decimal(10) ** 12)
    # Phase 10B: the store's own web addresses landing pages may use (e.g. a Shopify store's
    # custom domain), besides the platform's store address. Null keeps what is saved.
    landing_domains: list[str] | None = Field(default=None, max_length=10)


class ActionSettingsOut(BaseModel):
    engine_enabled: bool  # the installation's switch (ACTIONS_ENABLED)
    paused: bool
    landing_domains: list[str] = Field(default_factory=list)
    require_second_person: bool
    max_daily_budget: str | None
    currency: str  # the organization's reporting currency
    currency_minor_units: int
    increase_percent: int
    decrease_percent: int
    budget_change_interval_minutes: int
    daily_limit_per_account: int
    updated_at: datetime | None


class WriteAccessIn(BaseModel):
    allowed: bool


class WriteAccessOut(BaseModel):
    connection_id: uuid.UUID
    provider: str
    supported: bool  # the platform can be changed through AdVegaX at all
    allowed: bool
    allowed_at: datetime | None
    allowed_by: uuid.UUID | None
    missing_permissions: list[str]
    # Whether signing in again can grant the missing permissions (e.g. Meta's change login).
    can_request_permission: bool
