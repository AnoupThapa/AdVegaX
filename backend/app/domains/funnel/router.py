"""The funnel API (task 7-06, PLAN §8; API_SPECIFICATION §16)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ok
from app.domains.funnel.read_service import FunnelReadService
from app.domains.funnel.schemas import CampaignFunnelsOut, FunnelOut, LandingPagesOut

router = APIRouter(tags=["funnel"])
FUNNEL = "/organizations/{organization_id}/analytics/funnel"


def get_funnel(rt: RuntimeDep) -> FunnelReadService:
    return FunnelReadService(rt)


FunnelDep = Annotated[FunnelReadService, Depends(get_funnel)]
FromDay = Annotated[date | None, Query(alias="from")]
ToDay = Annotated[date | None, Query(alias="to")]
StoreId = Annotated[uuid.UUID | None, Query()]


@router.get(FUNNEL, response_model=Envelope[FunnelOut])
def analytics_funnel(
    ctx: TenantDep,
    svc: FunnelDep,
    from_day: FromDay = None,
    to_day: ToDay = None,
    store_id: StoreId = None,
) -> Envelope[FunnelOut]:
    """Impression → purchase for the period: each stage with its source, the steps (a rate only
    between stages of the same source), each platform's and channel's own funnel, and the
    drop-offs found by fixed rules (funnel-v1)."""
    return ok(svc.funnel(ctx, from_day=from_day, to_day=to_day, store_id=store_id))


@router.get(f"{FUNNEL}/campaigns", response_model=Envelope[CampaignFunnelsOut])
def analytics_funnel_campaigns(
    ctx: TenantDep,
    svc: FunnelDep,
    from_day: FromDay = None,
    to_day: ToDay = None,
    store_id: StoreId = None,
) -> Envelope[CampaignFunnelsOut]:
    """Each campaign's funnel as its platform reports it, Google Analytics' funnel for the
    campaign of the same name, and the other traffic."""
    return ok(svc.campaign_funnels(ctx, from_day=from_day, to_day=to_day, store_id=store_id))


@router.get(f"{FUNNEL}/landing-pages", response_model=Envelope[LandingPagesOut])
def analytics_funnel_landing_pages(
    ctx: TenantDep,
    svc: FunnelDep,
    from_day: FromDay = None,
    to_day: ToDay = None,
    store_id: StoreId = None,
) -> Envelope[LandingPagesOut]:
    """Google Analytics' funnel for each landing page, most visits first (at most 100)."""
    return ok(svc.landing_pages(ctx, from_day=from_day, to_day=to_day, store_id=store_id))
