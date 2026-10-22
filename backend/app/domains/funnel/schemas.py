"""Answers of the funnel API (Phase 7, task 7-06, PLAN §8).

Every answer carries the definition version (``funnel-v1``), the reporting currency and time
zone, the sources with how fresh they are, the stages' definitions, and an ``availability``
(with a reason) on every figure — never a 0 for missing data. A step has a ``rate`` only when
both its stages come from the same source (``kind`` says which, Q-7-2).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.domains.commerce.schemas import FigureOut
from app.domains.metrics.schemas import AnalyticsContextOut, MetricDefinitionOut


class StepOut(BaseModel):
    from_stage: str
    to_stage: str
    kind: str  # same_source | different_sources | store_conversion
    rate: FigureOut | None  # None: different sources — no rate


class PlatformFunnelOut(BaseModel):
    provider: str  # google_ads | meta_ads
    source: str  # platform_reported
    ad_accounts: int
    stages: dict[str, FigureOut]
    steps: list[StepOut]


class ChannelFunnelOut(BaseModel):
    channel: str
    stages: dict[str, FigureOut]
    steps: list[StepOut]


class FindingOut(BaseModel):
    view: str  # whole | platform | channel
    subject: str | None  # platform code or channel name
    from_stage: str
    to_stage: str
    rate: Decimal
    previous_rate: Decimal
    baseline_rate: Decimal
    events_before: Decimal
    change: Decimal  # relative change against the previous period (negative: a fall)


class RulesOut(BaseModel):
    drop_share: Decimal
    min_events: int
    baseline_days: int
    previous_from: date
    previous_to: date


class FunnelOut(AnalyticsContextOut):
    stages: dict[str, FigureOut]
    steps: list[StepOut]
    platforms: list[PlatformFunnelOut]
    platform_definitions: list[MetricDefinitionOut]
    channels: list[ChannelFunnelOut]
    channels_missing: FigureOut | None
    findings: list[FindingOut]
    rules: RulesOut


class CampaignFunnelOut(BaseModel):
    id: uuid.UUID
    ad_account_id: uuid.UUID
    provider: str
    source: str  # platform_reported
    name: str
    status: str
    stages: dict[str, FigureOut]
    steps: list[StepOut]
    # Google Analytics' funnel for the campaign of exactly the same name; null when there is
    # no property or a day was not read (see ``analytics_missing``).
    analytics: dict[str, FigureOut] | None
    analytics_steps: list[StepOut]
    shared_match: bool  # another campaign of the same name shares this match


class CampaignFunnelsOut(AnalyticsContextOut):
    items: list[CampaignFunnelOut]
    other_traffic: dict[str, FigureOut] | None
    other_traffic_steps: list[StepOut]
    website: dict[str, FigureOut] | None
    analytics_missing: FigureOut | None
    platform_definitions: list[MetricDefinitionOut]


class LandingPageFunnelOut(BaseModel):
    landing_page: str
    stages: dict[str, FigureOut]
    steps: list[StepOut]


class LandingPagesOut(AnalyticsContextOut):
    items: list[LandingPageFunnelOut]  # most visits first
    item_count: int
    items_missing: FigureOut | None
