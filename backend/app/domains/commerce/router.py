"""Stores, products and daily figures (task 2A-09, API_SPECIFICATION §5A, PLAN §11)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ok
from app.domains.commerce.read_service import MAX_PAGE_SIZE, CommerceReadService
from app.domains.commerce.schemas import (
    DailyMetricsOut,
    ProductOut,
    ProductPage,
    ResyncOut,
    StoreOut,
)

router = APIRouter(tags=["stores"])
ORG = "/organizations/{organization_id}"
STORE = f"{ORG}/stores/{{store_id}}"


def get_commerce(rt: RuntimeDep) -> CommerceReadService:
    return CommerceReadService(rt)


CommerceDep = Annotated[CommerceReadService, Depends(get_commerce)]


@router.get(f"{ORG}/stores", response_model=Envelope[list[StoreOut]])
def list_stores(ctx: TenantDep, svc: CommerceDep) -> Envelope[list[StoreOut]]:
    """Stores of this organization with their sync status and history limit."""
    return ok(svc.list_stores(ctx))


@router.get(STORE, response_model=Envelope[StoreOut])
def get_store(store_id: uuid.UUID, ctx: TenantDep, svc: CommerceDep) -> Envelope[StoreOut]:
    return ok(svc.get_store(ctx, store_id))


@router.post(
    f"{STORE}/resync", status_code=status.HTTP_202_ACCEPTED, response_model=Envelope[ResyncOut]
)
def resync_store(store_id: uuid.UUID, ctx: TenantDep, svc: CommerceDep) -> Envelope[ResyncOut]:
    """ "Sync now": a full check of the catalogue and recent orders (rate-limited per store)."""
    return ok(svc.resync(ctx, store_id))


@router.get(f"{STORE}/products", response_model=Envelope[ProductPage])
def list_products(
    store_id: uuid.UUID,
    ctx: TenantDep,
    svc: CommerceDep,
    cursor: Annotated[str | None, Query(max_length=600)] = None,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    q: Annotated[str | None, Query(max_length=100)] = None,
    product_status: Annotated[str | None, Query(alias="status", max_length=16)] = None,
) -> Envelope[ProductPage]:
    return ok(
        svc.list_products(
            ctx, store_id, cursor=cursor, page_size=page_size, search=q, status=product_status
        )
    )


@router.get(f"{STORE}/products/{{product_id}}", response_model=Envelope[ProductOut])
def get_product(
    store_id: uuid.UUID, product_id: uuid.UUID, ctx: TenantDep, svc: CommerceDep
) -> Envelope[ProductOut]:
    return ok(svc.get_product(ctx, store_id, product_id))


@router.get(f"{STORE}/metrics/daily", response_model=Envelope[DailyMetricsOut])
def daily_metrics(
    store_id: uuid.UUID,
    ctx: TenantDep,
    svc: CommerceDep,
    from_day: Annotated[date | None, Query(alias="from")] = None,
    to_day: Annotated[date | None, Query(alias="to")] = None,
) -> Envelope[DailyMetricsOut]:
    """Daily figures (store time zone, finance-v1) with availability; defaults to 30 days."""
    return ok(svc.daily_metrics(ctx, store_id, from_day=from_day, to_day=to_day))
