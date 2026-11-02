"""Campaign builder API schemas (Phase 10B, task 10B-05; API_SPECIFICATION §19K)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domains.actions.schemas import ActionCheckOut, ActionOut, DryRunOut

Platform = Literal["google_ads", "meta_ads"]
Match = Literal["phrase", "exact", "broad"]


class KeywordIn(BaseModel):
    text: str = Field(min_length=1, max_length=120)
    match: Match = "phrase"


class DraftCreateIn(BaseModel):
    """A draft for one platform of a ready strategy; AdVegaX fills in everything it can."""

    strategy_id: uuid.UUID
    platform: Platform
    ad_account_id: uuid.UUID | None = None  # needed when several accounts are linked
    creative_id: uuid.UUID | None = None  # default: the newest approved creative


class DraftUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    daily_budget: Decimal | None = Field(default=None, gt=0, lt=Decimal(10) ** 12)
    locations: list[str] | None = Field(default=None, max_length=20)
    age_min: int | None = Field(default=None, ge=18, le=65)
    age_max: int | None = Field(default=None, ge=18, le=65)
    keywords: list[KeywordIn] | None = Field(default=None, max_length=50)
    landing_url: str | None = Field(default=None, max_length=2048)
    meta_page_id: str | None = Field(default=None, max_length=32)
    meta_pixel_id: str | None = Field(default=None, max_length=32)
    remove_pixel: bool = False
    creative_id: uuid.UUID | None = None
    # Ticks the declarations (Google: no EU political advertising; Meta: no special ad
    # category). Any later change to the draft asks for it again.
    confirm_declarations: bool = False


class CreativeSummaryOut(BaseModel):
    id: uuid.UUID
    version: int
    status: str
    format: str
    angle: str
    content: dict[str, Any]
    asset_id: uuid.UUID | None


class DraftOut(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID
    product_title: str | None
    platform: Platform
    ad_account_id: uuid.UUID
    ad_account_name: str | None
    creative: CreativeSummaryOut
    name: str
    reference: str
    daily_budget: str
    monthly_estimate: str  # the daily budget times 30.4, computed by AdVegaX
    currency: str
    currency_minor_units: int
    locations: list[str]
    age_min: int
    age_max: int
    keywords: list[dict[str, str]]
    landing_url: str
    meta_page_id: str | None
    meta_pixel_id: str | None
    bidding: str  # maximize_conversions | maximize_clicks | purchases | link_clicks
    declarations_confirmed: bool
    version: int
    status: str  # draft | launching | created | live | failed | archived
    created_ids: dict[str, str]
    campaign_id: uuid.UUID | None  # AdVegaX's campaign, once a sync has read it
    error_code: str | None
    editable: bool
    open_action_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class DraftPreviewOut(BaseModel):
    """Every check and the platform's test of the draft; nothing is created."""

    draft: DraftOut
    passed: bool
    checks: list[ActionCheckOut]
    dry_run: DryRunOut
    budget_limits: dict[str, str | None]


class SupportedCountryOut(BaseModel):
    code: str


class MetaAssetOut(BaseModel):
    id: str
    name: str | None


__all__ = ["ActionOut"]
