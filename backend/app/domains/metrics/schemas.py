"""Answers of the unified analytics API (Phase 6, task 6-05, PLAN §8).

Every answer carries the definition version (``analytics-v1``), the reporting currency and time
zone, the sources it used with how fresh they are, the currencies it converted and from which
banks, and an ``availability`` (with a reason) on every figure — never a 0 for missing data.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.domains.commerce.schemas import FigureOut


class MetricDefinitionOut(BaseModel):
    key: str
    label: str
    unit: str  # money | count | ratio | multiple
    formula: str
    note: str | None
    sources: list[str]


class SourceOut(BaseModel):
    kind: str  # store | ad_account | analytics_property
    id: uuid.UUID
    provider: str
    name: str | None
    currency: str
    timezone: str
    synced_from: date | None  # first day read (the source's own days); null = still importing
    updated_at: datetime | None  # when its figures were last brought up to date


class ConversionOut(BaseModel):
    """A currency converted into the reporting currency in this answer."""

    currency: str
    rate_sources: list[str]  # ecb | nrb
    first_rate_date: date | None  # the oldest published rate used
    last_rate_date: date | None
    days_without_rate: int  # days whose figures are "not available — no exchange rate"


class AnalyticsContextOut(BaseModel):
    definition_version: str
    reporting_currency: str
    currency_minor_units: int
    reporting_timezone: str
    store_id: uuid.UUID | None  # null = the whole organization
    from_day: date
    to_day: date
    sources: list[SourceOut]
    conversions: list[ConversionOut]
    notes: list[str]  # plain message keys, e.g. time_zones_differ


class OverviewDayOut(BaseModel):
    day: date
    figures: dict[str, FigureOut]


class OverviewOut(AnalyticsContextOut):
    totals: dict[str, FigureOut]
    days: list[OverviewDayOut]
    definitions: list[MetricDefinitionOut]


class PlatformOut(BaseModel):
    provider: str  # google_ads | meta_ads
    source: str  # platform_reported
    ad_accounts: int
    figures: dict[str, FigureOut]


class AnalyticsChannelOut(BaseModel):
    channel: str  # GA4 default channel group
    figures: dict[str, FigureOut]


class ChannelsOut(AnalyticsContextOut):
    ad_spend: FigureOut  # all platforms together (the only figure added across them)
    platforms: list[PlatformOut]
    analytics_channels: list[AnalyticsChannelOut]
    analytics_channels_missing: FigureOut | None  # why there are no channels, if none


class CampaignOut(BaseModel):
    id: uuid.UUID
    ad_account_id: uuid.UUID
    provider: str  # google_ads | meta_ads
    source: str  # platform_reported
    name: str
    status: str
    budget_period: str | None  # daily | lifetime; budget use is against today's budget
    figures: dict[str, FigureOut]
    # Google Analytics' figures for the campaign of the same name (Q-6-9); null with
    # ``analytics_missing`` when no property is in scope or a day was not read.
    analytics: dict[str, FigureOut] | None
    analytics_missing: FigureOut | None


class CampaignsOut(AnalyticsContextOut):
    items: list[CampaignOut]


class ProductFiguresOut(BaseModel):
    product_id: uuid.UUID | None  # null: sold lines AdVegaX could not match to a product
    store_id: uuid.UUID
    title: str | None
    figures: dict[str, FigureOut]


class ProductsOut(AnalyticsContextOut):
    items: list[ProductFiguresOut]  # most net sales first
    items_missing: FigureOut | None  # why there are none (no store, a day not read)
    other_currency_lines: int  # sold lines in another currency, left out (never summed)
