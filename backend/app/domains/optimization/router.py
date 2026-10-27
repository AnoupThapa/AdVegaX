"""The recommendations API (Phase 11, task 11-06, PLAN §6; API_SPECIFICATION §19L)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ok
from app.domains.optimization.schemas import (
    OptimizationSettingsIn,
    OptimizationSettingsOut,
    RecommendationListOut,
    RecommendationOut,
    RecommendationRejectIn,
)
from app.domains.optimization.service import RecommendationService

router = APIRouter(tags=["recommendations"])
ORG = "/organizations/{organization_id}"
ONE = f"{ORG}/recommendations/{{recommendation_id}}"
Filter = Literal["open", "decided", "closed", "approved", "rejected", "done"]


def get_service(rt: RuntimeDep) -> RecommendationService:
    return RecommendationService(rt)


ServiceDep = Annotated[RecommendationService, Depends(get_service)]


@router.get(f"{ORG}/recommendations", response_model=Envelope[RecommendationListOut])
def list_recommendations(
    ctx: TenantDep,
    svc: ServiceDep,
    status: Filter | None = None,
    campaign_id: uuid.UUID | None = None,
) -> Envelope[RecommendationListOut]:
    """Open advice first, by rank; then decided and closed advice, newest first."""
    return ok(svc.list_recommendations(ctx, status=status, campaign_id=campaign_id))


@router.post(f"{ORG}/recommendations/refresh", response_model=Envelope[RecommendationListOut])
def refresh_recommendations(ctx: TenantDep, svc: ServiceDep) -> Envelope[RecommendationListOut]:
    """Look again now. Errors: REFRESH_LIMIT, OPTIMIZATION_DISABLED."""
    return ok(svc.refresh(ctx))


@router.get(ONE, response_model=Envelope[RecommendationOut])
def get_recommendation(
    recommendation_id: uuid.UUID, ctx: TenantDep, svc: ServiceDep
) -> Envelope[RecommendationOut]:
    return ok(svc.get(ctx, recommendation_id))


@router.post(f"{ONE}/approve", response_model=Envelope[RecommendationOut])
def approve_recommendation(
    recommendation_id: uuid.UUID, ctx: TenantDep, svc: ServiceDep
) -> Envelope[RecommendationOut]:
    """Checked again, then an Action Engine change (sent at once by an owner or admin).
    Errors: RECOMMENDATION_OUT_OF_DATE, RECOMMENDATION_CLOSED and the 10A errors."""
    return ok(svc.approve(ctx, recommendation_id))


@router.post(f"{ONE}/reject", response_model=Envelope[RecommendationOut])
def reject_recommendation(
    recommendation_id: uuid.UUID, body: RecommendationRejectIn, ctx: TenantDep, svc: ServiceDep
) -> Envelope[RecommendationOut]:
    return ok(svc.reject(ctx, recommendation_id, body))


@router.post(f"{ONE}/done", response_model=Envelope[RecommendationOut])
def recommendation_done(
    recommendation_id: uuid.UUID, ctx: TenantDep, svc: ServiceDep
) -> Envelope[RecommendationOut]:
    """Advice without a change: marked as looked into."""
    return ok(svc.done(ctx, recommendation_id))


@router.get(f"{ORG}/optimization-settings", response_model=Envelope[OptimizationSettingsOut])
def get_optimization_settings(ctx: TenantDep, svc: ServiceDep) -> Envelope[OptimizationSettingsOut]:
    return ok(svc.get_settings(ctx))


@router.put(f"{ORG}/optimization-settings", response_model=Envelope[OptimizationSettingsOut])
def put_optimization_settings(
    body: OptimizationSettingsIn, ctx: TenantDep, svc: ServiceDep
) -> Envelope[OptimizationSettingsOut]:
    return ok(svc.put_settings(ctx, body))
