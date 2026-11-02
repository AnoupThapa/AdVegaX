"""Organization, member and invitation endpoints (API_SPECIFICATION §4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import OrganizationsDep, PrincipalDep, TenantDep, VerifiedPrincipalDep
from app.api.responses import Envelope, ok
from app.domains.identity.schemas import StatusOut
from app.domains.organizations.schemas import (
    InvitationAccept,
    InvitationCreate,
    InvitationOut,
    MemberOut,
    MemberUpdate,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)

router = APIRouter(tags=["organizations"])
ORG = "/organizations/{organization_id}"


@router.get("/organizations", response_model=Envelope[list[OrganizationOut]])
def list_organizations(
    principal: PrincipalDep, orgs: OrganizationsDep
) -> Envelope[list[OrganizationOut]]:
    return ok(orgs.list_for_user(principal))


@router.post(
    "/organizations", status_code=status.HTTP_201_CREATED, response_model=Envelope[OrganizationOut]
)
def create_organization(
    body: OrganizationCreate, principal: VerifiedPrincipalDep, orgs: OrganizationsDep
) -> Envelope[OrganizationOut]:
    return ok(orgs.create(principal, body))


@router.get(ORG, response_model=Envelope[OrganizationOut])
def get_organization(ctx: TenantDep, orgs: OrganizationsDep) -> Envelope[OrganizationOut]:
    return ok(orgs.get(ctx))


@router.patch(ORG, response_model=Envelope[OrganizationOut])
def update_organization(
    body: OrganizationUpdate, ctx: TenantDep, orgs: OrganizationsDep
) -> Envelope[OrganizationOut]:
    return ok(orgs.update(ctx, body))


@router.get(f"{ORG}/members", response_model=Envelope[list[MemberOut]])
def list_members(ctx: TenantDep, orgs: OrganizationsDep) -> Envelope[list[MemberOut]]:
    return ok(orgs.list_members(ctx))


@router.patch(f"{ORG}/members/{{member_id}}", response_model=Envelope[MemberOut])
def update_member(
    member_id: uuid.UUID, body: MemberUpdate, ctx: TenantDep, orgs: OrganizationsDep
) -> Envelope[MemberOut]:
    return ok(orgs.update_member(ctx, member_id, role=body.role, status=body.status))


@router.delete(f"{ORG}/members/{{member_id}}", response_model=Envelope[StatusOut])
def remove_member(
    member_id: uuid.UUID, ctx: TenantDep, orgs: OrganizationsDep
) -> Envelope[StatusOut]:
    orgs.remove_member(ctx, member_id)
    return ok(StatusOut(status="removed"))


@router.post(
    f"{ORG}/invitations",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[InvitationOut],
)
def create_invitation(
    body: InvitationCreate, ctx: TenantDep, principal: PrincipalDep, orgs: OrganizationsDep
) -> Envelope[InvitationOut]:
    return ok(orgs.create_invitation(ctx, principal, email=body.email, role=body.role))


@router.get(f"{ORG}/invitations", response_model=Envelope[list[InvitationOut]])
def list_invitations(ctx: TenantDep, orgs: OrganizationsDep) -> Envelope[list[InvitationOut]]:
    return ok(orgs.list_invitations(ctx))


@router.delete(f"{ORG}/invitations/{{invitation_id}}", response_model=Envelope[StatusOut])
def revoke_invitation(
    invitation_id: uuid.UUID, ctx: TenantDep, orgs: OrganizationsDep
) -> Envelope[StatusOut]:
    orgs.revoke_invitation(ctx, invitation_id)
    return ok(StatusOut(status="revoked"))


@router.post("/invitations/accept", response_model=Envelope[OrganizationOut])
def accept_invitation(
    body: InvitationAccept, principal: VerifiedPrincipalDep, orgs: OrganizationsDep
) -> Envelope[OrganizationOut]:
    return ok(orgs.accept_invitation(principal, body.token))
