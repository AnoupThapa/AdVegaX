"""The agency API (Phase 14, tasks 14-03 and 14-04; API_SPECIFICATION §19O)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import Envelope, ok
from app.domains.agency.schemas import AgencyOut, ClientOut, CodeOut, GrantIn, GrantOut
from app.domains.agency.service import AgencyService

router = APIRouter(tags=["agency"])
ORG = "/organizations/{organization_id}"


def get_service(rt: RuntimeDep) -> AgencyService:
    return AgencyService(rt)


ServiceDep = Annotated[AgencyService, Depends(get_service)]


@router.get(f"{ORG}/agency", response_model=Envelope[AgencyOut])
def get_agency(ctx: TenantDep, svc: ServiceDep) -> Envelope[AgencyOut]:
    """Agencies with access to this organization, and organizations that gave it access."""
    return ok(svc.get(ctx))


@router.post(f"{ORG}/agency/code", response_model=Envelope[CodeOut])
def new_agency_code(ctx: TenantDep, svc: ServiceDep) -> Envelope[CodeOut]:
    """Owners and admins: a new agency code for clients to enter."""
    return ok(svc.new_code(ctx))


@router.post(f"{ORG}/agency/grants", response_model=Envelope[GrantOut], status_code=201)
def grant_agency(body: GrantIn, ctx: TenantDep, svc: ServiceDep) -> Envelope[GrantOut]:
    """Owners only: give the agency with this code access (pending its acceptance)."""
    return ok(svc.grant(ctx, body))


@router.post(f"{ORG}/agency/grants/{{grant_id}}/accept", response_model=Envelope[GrantOut])
def accept_grant(grant_id: uuid.UUID, ctx: TenantDep, svc: ServiceDep) -> Envelope[GrantOut]:
    """The agency's owners and admins."""
    return ok(svc.accept(ctx, grant_id))


@router.post(f"{ORG}/agency/grants/{{grant_id}}/revoke", response_model=Envelope[GrantOut])
def revoke_grant(grant_id: uuid.UUID, ctx: TenantDep, svc: ServiceDep) -> Envelope[GrantOut]:
    """Either side's owners and admins; at once."""
    return ok(svc.revoke(ctx, grant_id))


@router.get(f"{ORG}/clients", response_model=Envelope[list[ClientOut]])
def list_clients(ctx: TenantDep, svc: ServiceDep) -> Envelope[list[ClientOut]]:
    """The agency's clients, each computed on its own (no totals across clients)."""
    return ok(svc.clients(ctx))
