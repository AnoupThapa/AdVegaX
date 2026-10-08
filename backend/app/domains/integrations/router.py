"""Connection, resource and job endpoints (API_SPECIFICATION §5). No endpoint returns secrets."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse

from app.api.deps import IntegrationsDep, RuntimeDep, TenantDep, optional_principal
from app.api.responses import Envelope, ok
from app.domains.identity.principal import Principal
from app.domains.integrations.schemas import (
    AuthorizationStartOut,
    ConnectionOut,
    JobOut,
    LinkOut,
    ResourceOut,
)
from app.domains.jobs.service import get_job

router = APIRouter(tags=["connections"])
ORG = "/organizations/{organization_id}"
_MAX_PARAM = 2048


@router.get(f"{ORG}/connections", response_model=Envelope[list[ConnectionOut]])
def list_connections(ctx: TenantDep, svc: IntegrationsDep) -> Envelope[list[ConnectionOut]]:
    return ok(svc.list_connections(ctx))


@router.post(
    f"{ORG}/connections/{{provider}}/start", response_model=Envelope[AuthorizationStartOut]
)
def start_connection(
    provider: str, ctx: TenantDep, svc: IntegrationsDep
) -> Envelope[AuthorizationStartOut]:
    return ok(svc.start(ctx, provider))


@router.get("/connections/{provider}/callback", include_in_schema=False)
def connection_callback(
    provider: str,
    request: Request,
    svc: IntegrationsDep,
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> RedirectResponse:
    params = {k: v[:_MAX_PARAM] for k, v in request.query_params.items()}
    return RedirectResponse(
        svc.complete(principal, provider, params), status_code=status.HTTP_303_SEE_OTHER
    )


@router.get(f"{ORG}/connections/{{connection_id}}", response_model=Envelope[ConnectionOut])
def get_connection(
    connection_id: uuid.UUID, ctx: TenantDep, svc: IntegrationsDep
) -> Envelope[ConnectionOut]:
    return ok(svc.get_connection(ctx, connection_id))


@router.post(
    f"{ORG}/connections/{{connection_id}}/disconnect", response_model=Envelope[ConnectionOut]
)
def disconnect(
    connection_id: uuid.UUID, ctx: TenantDep, svc: IntegrationsDep
) -> Envelope[ConnectionOut]:
    return ok(svc.disconnect(ctx, connection_id))


@router.post(
    f"{ORG}/connections/{{connection_id}}/rediscover",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[JobOut],
)
def rediscover(connection_id: uuid.UUID, ctx: TenantDep, svc: IntegrationsDep) -> Envelope[JobOut]:
    return ok(svc.rediscover(ctx, connection_id))


@router.get(
    f"{ORG}/connections/{{connection_id}}/resources", response_model=Envelope[list[ResourceOut]]
)
def list_resources(
    connection_id: uuid.UUID, ctx: TenantDep, svc: IntegrationsDep
) -> Envelope[list[ResourceOut]]:
    return ok(svc.list_resources(ctx, connection_id))


@router.post(
    f"{ORG}/resources/{{resource_id}}/link",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[LinkOut],
)
def link_resource(
    resource_id: uuid.UUID, ctx: TenantDep, svc: IntegrationsDep
) -> Envelope[LinkOut]:
    return ok(svc.link(ctx, resource_id))


@router.post(f"{ORG}/resources/{{resource_id}}/unlink", response_model=Envelope[LinkOut])
def unlink_resource(
    resource_id: uuid.UUID, ctx: TenantDep, svc: IntegrationsDep
) -> Envelope[LinkOut]:
    return ok(svc.unlink(ctx, resource_id))


@router.get(f"{ORG}/resources/{{resource_id}}/links", response_model=Envelope[list[LinkOut]])
def link_history(
    resource_id: uuid.UUID, ctx: TenantDep, svc: IntegrationsDep
) -> Envelope[list[LinkOut]]:
    return ok(svc.link_history(ctx, resource_id))


@router.post(
    f"{ORG}/resources/{{resource_id}}/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[JobOut],
)
def sync_resource(resource_id: uuid.UUID, ctx: TenantDep, svc: IntegrationsDep) -> Envelope[JobOut]:
    return ok(svc.request_sync(ctx, resource_id))


@router.get(f"{ORG}/jobs/{{job_id}}", response_model=Envelope[JobOut])
def job_status(job_id: uuid.UUID, ctx: TenantDep, rt: RuntimeDep) -> Envelope[JobOut]:
    view = get_job(rt, ctx, job_id)
    return ok(
        JobOut(
            id=view.id,
            job_type=view.job_type,
            status=view.status,
            attempts=view.attempts,
            max_attempts=view.max_attempts,
            last_error_code=view.last_error_code,
        )
    )
