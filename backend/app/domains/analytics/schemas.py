"""Read API shapes for analytics properties and their daily figures (task 5-07, PLAN §10-§11).

Every figure is **reported by the platform** (``source``), in the property's currency and time
zone. Money is an exact decimal string; rates are derived on read (A5) and carry an
``availability`` with a reason instead of a 0 when they cannot be computed (A10). Days not read
yet are ``not_synchronized``; the last days are marked ``processing: true`` because the platform
is still processing them (Q-5-6).

**Users are distinct counts per day** (Q-5-5): they are given for a day, and never added up for
a period of several days or across views — a period's ``total_users`` is "unavailable" with
the reason ``users_per_day_only``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.domains.commerce.schemas import Availability, FigureOut


class AnalyticsSyncOut(BaseModel):
    running: bool
    mode: str | None  # initial | quick | nightly | weekly while running
    progress: int | None  # 0-100 during the first import
    waiting_for_allowance: bool  # Google is limiting how much AdVegaX can read for now
    last_quick_at: datetime | None
    last_nightly_at: datetime | None
    last_weekly_at: datetime | None
    last_error_code: str | None  # plain message key, never a platform message
    last_error_at: datetime | None


class AnalyticsHealthOut(BaseModel):
    """A plain message key (``no_property_access``, ``property_deleted``,
    ``property_details_changed``, ``rate_limited``), or None when all is well."""

    code: str | None
    checked_at: datetime | None


class AnalyticsPropertyOut(BaseModel):
    id: uuid.UUID
    resource_id: uuid.UUID
    provider: str
    source: str  # platform_reported: every figure is the platform's own
    external_property_id: str
    name: str | None
    account_name: str | None  # the Analytics account it sits in (display only)
    currency: str
    currency_minor_units: int
    timezone: str
    status: str  # importing | active | error | disconnected
    platform_status: str  # active | deleted
    linked: bool
    connection_status: str
    history_from: date | None
    first_import_completed_at: datetime | None
    sync: AnalyticsSyncOut
    health: AnalyticsHealthOut | None
    created_at: datetime


class AnalyticsQualityOut(BaseModel):
    """What the platform said about the figures (Q-5-8): shown, never hidden."""

    other_row: bool  # rare values were grouped into "(other)"
    thresholded: bool  # rows were withheld for privacy
    sampled: bool  # the figures are based on a sample
    truncated: bool  # not every value could be read


class AnalyticsFiguresOut(BaseModel):
    """Platform-reported measures for a day or a period, and the rates derived from them."""

    availability: Availability  # not_synchronized when (part of) the period is not read
    reason: str | None = None
    sessions: int | None
    engaged_sessions: int | None
    total_users: FigureOut  # one day only; "unavailable" (users_per_day_only) for a period
    new_users: int | None  # a person is new on one day only, so new users add up
    key_events: Decimal | None
    purchases: int | None
    purchase_revenue: Decimal | None  # purchases minus refunds: can be negative
    engagement_rate: FigureOut  # engaged sessions ÷ sessions (a fraction)
    key_events_per_session: FigureOut
    purchase_conversion_rate: FigureOut  # purchases ÷ sessions (a fraction)
    revenue_per_session: FigureOut
    quality: AnalyticsQualityOut


class AnalyticsDayOut(AnalyticsFiguresOut):
    day: date
    processing: bool  # True for the last days, which Google is still processing


class AnalyticsItemOut(BaseModel):
    """One channel, or one source / medium / campaign, with its figures for the period."""

    key: str
    channel_group: str | None
    source: str | None
    medium: str | None
    campaign: str | None
    figures: AnalyticsFiguresOut


class AnalyticsDailyMetricsOut(BaseModel):
    property_id: uuid.UUID
    source: str
    breakdown: str  # total | channel | source
    currency: str
    currency_minor_units: int
    timezone: str
    from_day: date
    to_day: date
    synced_from: date | None  # first day read (property time zone)
    processing_from: date  # days from this one on are still being processed by Google
    totals: AnalyticsFiguresOut
    days: list[AnalyticsDayOut]  # the total view only; empty for a breakdown
    items: list[AnalyticsItemOut]  # a breakdown only, most sessions first; empty for total
    item_count: int  # every value of the breakdown in the period (items may be fewer)


class AnalyticsResyncOut(BaseModel):
    property_id: uuid.UUID
    job_id: uuid.UUID
    mode: str
