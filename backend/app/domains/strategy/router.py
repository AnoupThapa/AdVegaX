"""The campaign strategy API (Phase 8, task 8-05, PLAN §7; API_SPECIFICATION §19H)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ListEnvelope, ok, ok_list
from app.domains.strategy.schemas import (
    StrategyCreateIn,
    StrategyOut,
    StrategySummaryOut,
    StrategyUpdateIn,
    UsageOut,
)
from app.domains.strategy.service import StrategyService

router = APIRouter(tags=["strategies"])
BASE = "/organizations/{organization_id}/ai"
ONE = f"{BASE}/campaign-strategies/{{strategy_id}}"


def get_strategies(rt: RuntimeDep) -> StrategyService:
    return StrategyService(rt)


StrategiesDep = Annotated[StrategyService, Depends(get_strategies)]


@router.post(
    f"{BASE}/campaign-strategies",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[StrategyOut],
)
def generate_campaign_strategy(
    body: StrategyCreateIn, ctx: TenantDep, svc: StrategiesDep
) -> Envelope[StrategyOut]:
    """Ask the planner for a strategy for one product, the chosen platforms and the merchant's
    budget. The answer is validated before it is kept as a draft; nothing is created at Google
    or Meta. Errors: AI_LIMIT_REACHED, AI_UNAVAILABLE, AI_ANSWER_REJECTED,
    PRODUCT_NOT_PLANNABLE."""
    return ok(svc.generate(ctx, body))


@router.get(f"{BASE}/campaign-strategies", response_model=ListEnvelope[StrategySummaryOut])
def list_campaign_strategies(
    ctx: TenantDep,
    svc: StrategiesDep,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    status_filter: Annotated[
        Literal["draft", "ready", "archived"] | None, Query(alias="status")
    ] = None,
    product_id: uuid.UUID | None = None,
) -> ListEnvelope[StrategySummaryOut]:
    """Strategies, most recently changed first; archived ones only when asked for."""
    items, total = svc.list_strategies(
        ctx, page=page, page_size=page_size, status=status_filter, product_id=product_id
    )
    return ok_list(items, page=page, page_size=page_size, total=total)


@router.get(ONE, response_model=Envelope[StrategyOut])
def get_campaign_strategy(
    strategy_id: uuid.UUID, ctx: TenantDep, svc: StrategiesDep
) -> Envelope[StrategyOut]:
    """One strategy with its budget amounts, its evidence (the figures as the planner saw them)
    and the AI run, model and prompt version it came from."""
    return ok(svc.get(ctx, strategy_id))


@router.patch(ONE, response_model=Envelope[StrategyOut])
def update_campaign_strategy(
    strategy_id: uuid.UUID, body: StrategyUpdateIn, ctx: TenantDep, svc: StrategiesDep
) -> Envelope[StrategyOut]:
    """Edit the strategy and/or its budget. Re-validated with the same checks as the planner's
    answers; an edited strategy is a draft again."""
    return ok(svc.update(ctx, strategy_id, body))


@router.post(f"{ONE}/ready", response_model=Envelope[StrategyOut])
def mark_campaign_strategy_ready(
    strategy_id: uuid.UUID, ctx: TenantDep, svc: StrategiesDep
) -> Envelope[StrategyOut]:
    """Ready for the campaign builder (Phase 10B). Nothing is created yet."""
    return ok(svc.mark_ready(ctx, strategy_id))


@router.post(f"{ONE}/archive", response_model=Envelope[StrategyOut])
def archive_campaign_strategy(
    strategy_id: uuid.UUID, ctx: TenantDep, svc: StrategiesDep
) -> Envelope[StrategyOut]:
    """Archive (kept, never deleted; can no longer be changed)."""
    return ok(svc.archive(ctx, strategy_id))


@router.get(f"{BASE}/usage", response_model=Envelope[UsageOut])
def ai_usage(ctx: TenantDep, svc: StrategiesDep) -> Envelope[UsageOut]:
    """AI runs, tokens and estimated cost today and over 30 days (owners and admins)."""
    return ok(svc.usage(ctx))
