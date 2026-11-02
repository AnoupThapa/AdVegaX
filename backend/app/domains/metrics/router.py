"""Unified analytics: overview and channels (task 6-05, PLAN §8; API_SPECIFICATION §15)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ok
from app.domains.metrics.read_service import MetricsReadService
from app.domains.metrics.schemas import CampaignsOut, ChannelsOut, OverviewOut, ProductsOut

router = APIRouter(tags=["unified analytics"])
ANALYTICS = "/organizations/{organization_id}/analytics"


def get_metrics(rt: RuntimeDep) -> MetricsReadService:
    return MetricsReadService(rt)


MetricsDep = Annotated[MetricsReadService, Depends(get_metrics)]
FromDay = Annotated[date | None, Query(alias="from")]
ToDay = Annotated[date | None, Query(alias="to")]
StoreId = Annotated[uuid.UUID | None, Query()]


@router.get(f"{ANALYTICS}/overview", response_model=Envelope[OverviewOut])
def analytics_overview(
    ctx: TenantDep,
    svc: MetricsDep,
    from_day: FromDay = None,
    to_day: ToDay = None,
    store_id: StoreId = None,
) -> Envelope[OverviewOut]:
    """Sales, ad spend and profit together, in the reporting currency (analytics-v1), by day
    and for the period, with sources, freshness and the exchange rates used."""
    return ok(svc.overview(ctx, from_day=from_day, to_day=to_day, store_id=store_id))


@router.get(f"{ANALYTICS}/channels", response_model=Envelope[ChannelsOut])
def analytics_channels(
    ctx: TenantDep,
    svc: MetricsDep,
    from_day: FromDay = None,
    to_day: ToDay = None,
    store_id: StoreId = None,
) -> Envelope[ChannelsOut]:
    """Each ad platform's own reported figures, and Google Analytics' channels."""
    return ok(svc.channels(ctx, from_day=from_day, to_day=to_day, store_id=store_id))


@router.get(f"{ANALYTICS}/campaigns", response_model=Envelope[CampaignsOut])
def analytics_campaigns(
    ctx: TenantDep,
    svc: MetricsDep,
    from_day: FromDay = None,
    to_day: ToDay = None,
    store_id: StoreId = None,
) -> Envelope[CampaignsOut]:
    """Every campaign's platform-reported figures, budget use against today's budget, and
    Google Analytics' figures for the campaign of the same name."""
    return ok(svc.campaigns(ctx, from_day=from_day, to_day=to_day, store_id=store_id))


@router.get(f"{ANALYTICS}/products", response_model=Envelope[ProductsOut])
def analytics_products(
    ctx: TenantDep,
    svc: MetricsDep,
    from_day: FromDay = None,
    to_day: ToDay = None,
    store_id: StoreId = None,
) -> Envelope[ProductsOut]:
    """Every product sold: units, net sales, product cost, gross profit and margin."""
    return ok(svc.products(ctx, from_day=from_day, to_day=to_day, store_id=store_id))
