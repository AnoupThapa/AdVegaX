"""The Admin portal API (Phase 16, task 16-05; API_SPECIFICATION §19P)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import RuntimeDep, VerifiedPrincipalDep
from app.api.responses import Envelope, ok
from app.domains.platform.schemas import (
    AdminMeOut,
    AdminOrganizationOut,
    AdminUserOut,
    CodeIn,
    HealthOut,
    SettingIn,
    SettingOut,
    StatusIn,
    TotpSetupOut,
)
from app.domains.platform.service import AdminService

router = APIRouter(prefix="/admin", tags=["admin"])


def get_service(rt: RuntimeDep) -> AdminService:
    return AdminService(rt)


ServiceDep = Annotated[AdminService, Depends(get_service)]
Me = VerifiedPrincipalDep


@router.get("/me", response_model=Envelope[AdminMeOut])
def admin_me(me: Me, svc: ServiceDep) -> Envelope[AdminMeOut]:
    """Anyone signed in: whether they are an administrator and have entered their code."""
    return ok(svc.me(me))


@router.post("/two-step/setup", response_model=Envelope[TotpSetupOut])
def two_step_setup(me: Me, svc: ServiceDep) -> Envelope[TotpSetupOut]:
    return ok(svc.setup(me))


@router.post("/two-step/enable", response_model=Envelope[AdminMeOut])
def two_step_enable(body: CodeIn, me: Me, svc: ServiceDep) -> Envelope[AdminMeOut]:
    return ok(svc.enable(me, body.code))


@router.post("/two-step/verify", response_model=Envelope[AdminMeOut])
def two_step_verify(body: CodeIn, me: Me, svc: ServiceDep) -> Envelope[AdminMeOut]:
    return ok(svc.verify(me, body.code))


@router.get("/settings", response_model=Envelope[list[SettingOut]])
def list_settings(me: Me, svc: ServiceDep) -> Envelope[list[SettingOut]]:
    """Keys and switches: never a secret's value, only whether it is set and its last four."""
    return ok(svc.settings(me))


@router.put("/settings/{name}", response_model=Envelope[list[SettingOut]])
def save_setting(name: str, body: SettingIn, me: Me, svc: ServiceDep) -> Envelope[list[SettingOut]]:
    return ok(svc.save(me, name, body.value))


@router.delete("/settings/{name}", response_model=Envelope[list[SettingOut]])
def clear_setting(name: str, me: Me, svc: ServiceDep) -> Envelope[list[SettingOut]]:
    """Back to the settings file's value."""
    return ok(svc.clear(me, name))


@router.get("/organizations", response_model=Envelope[list[AdminOrganizationOut]])
def list_organizations(me: Me, svc: ServiceDep) -> Envelope[list[AdminOrganizationOut]]:
    return ok(svc.organizations(me))


@router.put(
    "/organizations/{organization_id}/status", response_model=Envelope[AdminOrganizationOut]
)
def set_organization_status(
    organization_id: uuid.UUID, body: StatusIn, me: Me, svc: ServiceDep
) -> Envelope[AdminOrganizationOut]:
    return ok(svc.set_status(me, organization_id, body.status))


@router.get("/users", response_model=Envelope[list[AdminUserOut]])
def list_users(me: Me, svc: ServiceDep) -> Envelope[list[AdminUserOut]]:
    return ok(svc.users(me))


@router.get("/health", response_model=Envelope[HealthOut])
def admin_health(me: Me, svc: ServiceDep) -> Envelope[HealthOut]:
    return ok(svc.health(me))
