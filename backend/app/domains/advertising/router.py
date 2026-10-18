"""Ad accounts, campaigns and their daily figures (task 3-08, PLAN §11)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ok
from app.domains.advertising.read_service import AdvertisingReadService
from app.domains.advertising.schemas import (
    AdAccountOut,
    AdCampaignDetailOut,
    AdCampaignListOut,
    AdDailyMetricsOut,
    AdResyncOut,
)

router = APIRouter(tags=["advertising"])
ORG = "/organizations/{organization_id}"
ACCOUNT = f"{ORG}/ad-accounts/{{ad_account_id}}"


def get_advertising(rt: RuntimeDep) -> AdvertisingReadService:
    return AdvertisingReadService(rt)


AdsDep = Annotated[AdvertisingReadService, Depends(get_advertising)]
FromDay = Annotated[date | None, Query(alias="from")]
ToDay = Annotated[date | None, Query(alias="to")]


@router.get(f"{ORG}/ad-accounts", response_model=Envelope[list[AdAccountOut]])
def list_ad_accounts(ctx: TenantDep, svc: AdsDep) -> Envelope[list[AdAccountOut]]:
    """Ad accounts of this organization with their sync status and health."""
    return ok(svc.list_accounts(ctx))


@router.get(ACCOUNT, response_model=Envelope[AdAccountOut])
def get_ad_account(ad_account_id: uuid.UUID, ctx: TenantDep, svc: AdsDep) -> Envelope[AdAccountOut]:
    return ok(svc.get_account(ctx, ad_account_id))


@router.post(
    f"{ACCOUNT}/resync", status_code=status.HTTP_202_ACCEPTED, response_model=Envelope[AdResyncOut]
)
def resync_ad_account(
    ad_account_id: uuid.UUID, ctx: TenantDep, svc: AdsDep
) -> Envelope[AdResyncOut]:
    """ "Sync now": the structure and the last 30 days (limited per account)."""
    return ok(svc.resync(ctx, ad_account_id))


@router.get(f"{ACCOUNT}/metrics/daily", response_model=Envelope[AdDailyMetricsOut])
def ad_account_daily_metrics(
    ad_account_id: uuid.UUID,
    ctx: TenantDep,
    svc: AdsDep,
    from_day: FromDay = None,
    to_day: ToDay = None,
) -> Envelope[AdDailyMetricsOut]:
    """Account-level daily figures (account time zone, platform-reported); 30 days by default."""
    return ok(svc.daily_metrics(ctx, ad_account_id, from_day=from_day, to_day=to_day))


@router.get(f"{ACCOUNT}/campaigns", response_model=Envelope[AdCampaignListOut])
def list_ad_campaigns(
    ad_account_id: uuid.UUID,
    ctx: TenantDep,
    svc: AdsDep,
    from_day: FromDay = None,
    to_day: ToDay = None,
) -> Envelope[AdCampaignListOut]:
    """Every campaign (removed ones included) with its figures for the period."""
    return ok(svc.list_campaigns(ctx, ad_account_id, from_day=from_day, to_day=to_day))


@router.get(f"{ORG}/campaigns/{{campaign_id}}", response_model=Envelope[AdCampaignDetailOut])
def get_ad_campaign(
    campaign_id: uuid.UUID,
    ctx: TenantDep,
    svc: AdsDep,
    from_day: FromDay = None,
    to_day: ToDay = None,
) -> Envelope[AdCampaignDetailOut]:
    """One campaign with its budget, ad groups and ads, each with its period figures."""
    return ok(svc.get_campaign(ctx, campaign_id, from_day=from_day, to_day=to_day))
