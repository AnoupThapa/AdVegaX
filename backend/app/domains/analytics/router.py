"""Analytics properties and their daily figures (task 5-07, PLAN §11)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ok
from app.domains.analytics.read_service import MAX_ITEMS, AnalyticsReadService
from app.domains.analytics.schemas import (
    AnalyticsDailyMetricsOut,
    AnalyticsPropertyOut,
    AnalyticsResyncOut,
    StoreAssignmentIn,
)

router = APIRouter(tags=["analytics"])
ORG = "/organizations/{organization_id}"
PROPERTY = f"{ORG}/analytics-properties/{{property_id}}"


def get_analytics(rt: RuntimeDep) -> AnalyticsReadService:
    return AnalyticsReadService(rt)


AnalyticsDep = Annotated[AnalyticsReadService, Depends(get_analytics)]
FromDay = Annotated[date | None, Query(alias="from")]
ToDay = Annotated[date | None, Query(alias="to")]
Breakdown = Annotated[Literal["total", "channel", "source"], Query()]
Limit = Annotated[int, Query(ge=1, le=MAX_ITEMS)]


@router.get(f"{ORG}/analytics-properties", response_model=Envelope[list[AnalyticsPropertyOut]])
def list_analytics_properties(
    ctx: TenantDep, svc: AnalyticsDep
) -> Envelope[list[AnalyticsPropertyOut]]:
    """Analytics properties of this organization with their sync status and health."""
    return ok(svc.list_properties(ctx))


@router.get(PROPERTY, response_model=Envelope[AnalyticsPropertyOut])
def get_analytics_property(
    property_id: uuid.UUID, ctx: TenantDep, svc: AnalyticsDep
) -> Envelope[AnalyticsPropertyOut]:
    return ok(svc.get_property(ctx, property_id))


@router.put(f"{PROPERTY}/store", response_model=Envelope[AnalyticsPropertyOut])
def assign_analytics_property_store(
    property_id: uuid.UUID, body: StoreAssignmentIn, ctx: TenantDep, svc: AnalyticsDep
) -> Envelope[AnalyticsPropertyOut]:
    """Which store the property measures; null = the whole organization (Phase 6)."""
    return ok(svc.assign_store(ctx, property_id, body.store_id))


@router.post(
    f"{PROPERTY}/resync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[AnalyticsResyncOut],
)
def resync_analytics_property(
    property_id: uuid.UUID, ctx: TenantDep, svc: AnalyticsDep
) -> Envelope[AnalyticsResyncOut]:
    """ "Sync now": the last 14 days (limited per property)."""
    return ok(svc.resync(ctx, property_id))


@router.get(f"{PROPERTY}/metrics/daily", response_model=Envelope[AnalyticsDailyMetricsOut])
def analytics_property_daily_metrics(
    property_id: uuid.UUID,
    ctx: TenantDep,
    svc: AnalyticsDep,
    from_day: FromDay = None,
    to_day: ToDay = None,
    breakdown: Breakdown = "total",
    limit: Limit = 100,
) -> Envelope[AnalyticsDailyMetricsOut]:
    """Daily figures in the property's time zone, reported by the platform (30 days by
    default): the total view day by day, or a breakdown by channel or by source / medium /
    campaign. Users are given per day only."""
    return ok(
        svc.daily_metrics(
            ctx, property_id, from_day=from_day, to_day=to_day, breakdown=breakdown, limit=limit
        )
    )
