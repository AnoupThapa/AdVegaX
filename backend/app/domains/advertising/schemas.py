"""Read API shapes for ad accounts, campaigns and their daily figures (task 3-08, PLAN §10-§11).

Every figure is **reported by the platform** (``source``), in the ad account's currency and
time zone. Money is an exact decimal string; rates are derived on read (A5) and carry an
``availability`` with a reason instead of a 0 when they cannot be computed (A10). Days not
read yet are ``not_synchronized``; the last days are marked ``settled: false`` because the
platform still changes them.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.domains.commerce.schemas import Availability, FigureOut


class AdSyncOut(BaseModel):
    running: bool
    mode: str | None  # initial | quick | nightly | weekly while running
    progress: int | None  # 0-100 during the first import
    waiting_for_allowance: bool  # the shared platform allowance is used up for now
    last_quick_at: datetime | None
    last_nightly_at: datetime | None
    last_weekly_at: datetime | None
    last_error_code: str | None  # plain message key, never a platform message
    last_error_at: datetime | None


class AdHealthOut(BaseModel):
    """A plain message key (``account_not_enabled``, ``no_account_access``,
    ``developer_token_not_approved``, ``account_details_changed``), or None."""

    code: str | None
    checked_at: datetime | None


class AdAccountOut(BaseModel):
    id: uuid.UUID
    resource_id: uuid.UUID
    provider: str
    source: str  # platform_reported: every figure is the platform's own
    external_account_id: str
    name: str | None
    group_path: str | None  # e.g. the manager accounts above it (display only)
    currency: str
    currency_minor_units: int
    timezone: str
    status: str  # importing | active | error | disconnected
    platform_status: str  # active | not_enabled | cancelled | suspended | closed
    linked: bool
    connection_status: str
    history_from: date | None
    first_import_completed_at: datetime | None
    sync: AdSyncOut
    health: AdHealthOut | None
    created_at: datetime


class AdFiguresOut(BaseModel):
    """Platform-reported measures for a day or a period, and the rates derived from them."""

    availability: Availability  # not_synchronized when (part of) the period is not read
    reason: str | None = None
    impressions: int | None
    clicks: int | None
    cost: Decimal | None
    conversions: Decimal | None
    conversion_value: Decimal | None
    click_through_rate: FigureOut  # clicks ÷ impressions (a fraction)
    cost_per_click: FigureOut  # cost ÷ clicks
    cost_per_conversion: FigureOut  # cost ÷ conversions
    conversion_value_per_cost: FigureOut  # conversion value ÷ cost (platform-reported)


class AdDayOut(AdFiguresOut):
    day: date
    settled: bool  # False for the last days, which the platform may still change


class AdDailyMetricsOut(BaseModel):
    ad_account_id: uuid.UUID
    source: str
    currency: str
    currency_minor_units: int
    timezone: str
    from_day: date
    to_day: date
    synced_from: date | None  # first day read (account time zone)
    settled_until: date  # days after this may still change
    days: list[AdDayOut]
    totals: AdFiguresOut


class AdBudgetOut(BaseModel):
    name: str | None
    period: str  # daily | lifetime
    amount: Decimal | None  # None when the platform gives none (never 0)
    currency: str
    shared: bool


class AdOut(BaseModel):
    id: uuid.UUID
    external_id: str
    name: str | None
    status: str
    platform_type: str | None
    figures: AdFiguresOut


class AdGroupOut(BaseModel):
    id: uuid.UUID
    external_id: str
    name: str
    status: str
    platform_type: str | None
    budget: AdBudgetOut | None
    figures: AdFiguresOut
    ads: list[AdOut]


class AdCampaignOut(BaseModel):
    id: uuid.UUID
    ad_account_id: uuid.UUID
    external_id: str
    name: str
    status: str  # active | paused | archived | removed
    platform_type: str | None  # shown as the platform names it, never computed on
    bidding_strategy_type: str | None
    start_date: date | None
    end_date: date | None
    budget: AdBudgetOut | None
    figures: AdFiguresOut


class AdCampaignListOut(BaseModel):
    ad_account_id: uuid.UUID
    source: str
    currency: str
    currency_minor_units: int
    from_day: date
    to_day: date
    items: list[AdCampaignOut]


class AdCampaignDetailOut(AdCampaignOut):
    provider: str
    source: str
    synced_from: date | None  # first day read for the ad account
    currency: str
    currency_minor_units: int
    from_day: date
    to_day: date
    ad_groups: list[AdGroupOut]


class AdResyncOut(BaseModel):
    ad_account_id: uuid.UUID
    job_id: uuid.UUID
    mode: str
