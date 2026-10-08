"""Shared request dependencies: runtime, principal (authentication) and tenant (authorization)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Path, Request

from app.core.errors import EmailNotVerified, Unauthenticated
from app.core.request_meta import RequestMeta, request_meta
from app.domains.identity.principal import Principal
from app.domains.identity.service import IdentityService
from app.domains.organizations.service import OrganizationService
from app.domains.organizations.tenancy import TenantContext
from app.runtime import Runtime


def get_runtime(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]


def get_identity(rt: RuntimeDep) -> IdentityService:
    return IdentityService(rt)


IdentityDep = Annotated[IdentityService, Depends(get_identity)]


def get_organizations(rt: RuntimeDep, identity: IdentityDep) -> OrganizationService:
    return OrganizationService(rt, identity)


OrganizationsDep = Annotated[OrganizationService, Depends(get_organizations)]


def get_meta(request: Request, rt: RuntimeDep) -> RequestMeta:
    return request_meta(request, rt.settings)


MetaDep = Annotated[RequestMeta, Depends(get_meta)]


def session_token(request: Request, rt: RuntimeDep) -> str | None:
    return request.cookies.get(rt.settings.SESSION_COOKIE_NAME)


SessionTokenDep = Annotated[str | None, Depends(session_token)]


def optional_principal(token: SessionTokenDep, identity: IdentityDep) -> Principal | None:
    return identity.authenticate(token)


def require_principal(
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Principal:
    if principal is None:
        raise Unauthenticated()
    return principal


PrincipalDep = Annotated[Principal, Depends(require_principal)]


def require_verified(principal: PrincipalDep) -> Principal:
    if not principal.email_verified:
        raise EmailNotVerified()
    return principal


VerifiedPrincipalDep = Annotated[Principal, Depends(require_verified)]


def tenant_context(
    organization_id: Annotated[uuid.UUID, Path()],
    principal: PrincipalDep,
    organizations: OrganizationsDep,
) -> TenantContext:
    """The URL organization ID is only a claim; membership is resolved server-side."""
    return organizations.resolve_tenant(principal, organization_id)


TenantDep = Annotated[TenantContext, Depends(tenant_context)]
