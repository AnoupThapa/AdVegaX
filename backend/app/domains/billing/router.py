"""The billing API (Phase 13, task 13-06, PLAN §6; API_SPECIFICATION §19N)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import RuntimeDep, TenantDep, VerifiedPrincipalDep
from app.api.responses import Envelope, ok
from app.domains.billing.schemas import BillingOut, CheckoutIn, PlanOut, RedirectOut
from app.domains.billing.service import BillingService, receive_webhook

router = APIRouter(tags=["billing"])
ORG = "/organizations/{organization_id}"


def get_service(rt: RuntimeDep) -> BillingService:
    return BillingService(rt)


ServiceDep = Annotated[BillingService, Depends(get_service)]


@router.get("/billing/plans", response_model=Envelope[list[PlanOut]])
def list_plans(_: VerifiedPrincipalDep, svc: ServiceDep) -> Envelope[list[PlanOut]]:
    """The plans, their prices (minor units, GST included) and limits."""
    return ok(svc.plans())


@router.get(f"{ORG}/billing", response_model=Envelope[BillingOut])
def get_billing(ctx: TenantDep, svc: ServiceDep) -> Envelope[BillingOut]:
    """Every member: the plan in force, its dates, limits and usage."""
    return ok(svc.get(ctx))


@router.post(f"{ORG}/billing/checkout", response_model=Envelope[RedirectOut])
def start_checkout(body: CheckoutIn, ctx: TenantDep, svc: ServiceDep) -> Envelope[RedirectOut]:
    """Owners only. Errors: CONFLICT (already subscribed: use the portal), BILLING_UNAVAILABLE."""
    return ok(svc.checkout(ctx, body))


@router.post(f"{ORG}/billing/portal", response_model=Envelope[RedirectOut])
def open_portal(ctx: TenantDep, svc: ServiceDep) -> Envelope[RedirectOut]:
    """Owners only. Errors: CONFLICT (no Stripe customer yet), BILLING_UNAVAILABLE."""
    return ok(svc.portal(ctx))


@router.post("/billing/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, rt: RuntimeDep) -> Envelope[dict[str, str]]:
    """Public: Stripe's signature over the raw body is the authentication."""
    body = await request.body()
    signature = request.headers.get("stripe-signature")
    outcome = await run_in_threadpool(receive_webhook, rt, body, signature)
    return ok({"status": outcome})
