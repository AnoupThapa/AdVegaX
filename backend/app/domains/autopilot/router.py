"""The autopilot API (Phase 12, task 12-05, PLAN §6; API_SPECIFICATION §19M)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ok
from app.domains.autopilot.schemas import (
    AutopilotEnableIn,
    AutopilotPolicyIn,
    AutopilotPolicyOut,
    AutopilotRunOut,
)
from app.domains.autopilot.service import AutopilotService

router = APIRouter(tags=["autopilot"])
ORG = "/organizations/{organization_id}"


def get_service(rt: RuntimeDep) -> AutopilotService:
    return AutopilotService(rt)


ServiceDep = Annotated[AutopilotService, Depends(get_service)]


@router.get(f"{ORG}/autopilot", response_model=Envelope[AutopilotPolicyOut])
def get_autopilot(ctx: TenantDep, svc: ServiceDep) -> Envelope[AutopilotPolicyOut]:
    """The policy, readiness and the installation's ceilings."""
    return ok(svc.get(ctx))


@router.put(f"{ORG}/autopilot", response_model=Envelope[AutopilotPolicyOut])
def put_autopilot(
    body: AutopilotPolicyIn, ctx: TenantDep, svc: ServiceDep
) -> Envelope[AutopilotPolicyOut]:
    """Owners only. Limits may only be stricter than the installation's ceilings."""
    return ok(svc.put(ctx, body))


@router.post(f"{ORG}/autopilot/enable", response_model=Envelope[AutopilotPolicyOut])
def enable_autopilot(
    body: AutopilotEnableIn, ctx: TenantDep, svc: ServiceDep
) -> Envelope[AutopilotPolicyOut]:
    """Owners only, with the organization's name typed. Errors: AUTOPILOT_CONFIRMATION,
    AUTOPILOT_NOT_READY."""
    return ok(svc.enable(ctx, body))


@router.post(f"{ORG}/autopilot/stop", response_model=Envelope[AutopilotPolicyOut])
def stop_autopilot(ctx: TenantDep, svc: ServiceDep) -> Envelope[AutopilotPolicyOut]:
    """Owner, admin or manager; takes effect at once."""
    return ok(svc.stop(ctx))


@router.get(f"{ORG}/autopilot/runs", response_model=Envelope[list[AutopilotRunOut]])
def list_autopilot_runs(ctx: TenantDep, svc: ServiceDep) -> Envelope[list[AutopilotRunOut]]:
    return ok(svc.runs(ctx))
