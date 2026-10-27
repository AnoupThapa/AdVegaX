"""Shared request dependencies: runtime, principal (authentication) and tenant (authorization)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Path, Request

from app.core.errors import EmailNotVerified, OrganizationReadOnly, Unauthenticated
from app.core.request_meta import RequestMeta, request_meta
from app.domains.billing.entitlements import is_read_only
from app.domains.identity.principal import Principal
from app.domains.identity.service import IdentityService
from app.domains.integrations.service import IntegrationService
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


def get_integrations(rt: RuntimeDep, organizations: OrganizationsDep) -> IntegrationService:
    return IntegrationService(rt, organizations)


IntegrationsDep = Annotated[IntegrationService, Depends(get_integrations)]


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


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Phase 13 (Q-13-2, Q-13-7): what a read-only organization may still change — its billing, its
# name and people, and switching things off or cancelling. Everything else is refused with
# ORGANIZATION_READ_ONLY; the service-level checks (``billing.entitlements``) back this up.
READ_ONLY_ALLOWED = frozenset(
    {
        "",
        "/billing/checkout",
        "/billing/portal",
        "/invitations",
        "/invitations/{invitation_id}",
        "/members/{member_id}",
        "/autopilot/stop",
        "/actions/{action_id}/cancel",
        "/actions/{action_id}/reject",
        "/recommendations/{recommendation_id}/reject",
        "/connections/{connection_id}/disconnect",
        "/resources/{resource_id}/unlink",
    }
)
ORG_PATH = "{organization_id}"


def _route_tail(request: Request) -> str | None:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if not isinstance(template, str) or ORG_PATH not in template:
        return None
    return template.split(ORG_PATH, 1)[1]


def tenant_context(
    organization_id: Annotated[uuid.UUID, Path()],
    principal: PrincipalDep,
    organizations: OrganizationsDep,
    request: Request,
    rt: RuntimeDep,
) -> TenantContext:
    """The URL organization ID is only a claim; membership is resolved server-side. While
    billing is on, a read-only organization (trial over, or payment failed past its grace)
    may only read, plus the few changes in ``READ_ONLY_ALLOWED``."""
    ctx = organizations.resolve_tenant(principal, organization_id)
    writing = request.method not in SAFE_METHODS
    if rt.settings.BILLING_ENABLED and writing and _route_tail(request) not in READ_ONLY_ALLOWED:
        with rt.db.transaction(org_id=ctx.organization_id) as session:
            if is_read_only(rt, session, ctx.organization_id):
                raise OrganizationReadOnly()
    return ctx


TenantDep = Annotated[TenantContext, Depends(tenant_context)]
