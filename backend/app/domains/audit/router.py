"""Audit log read endpoint (API_SPECIFICATION §18)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import RuntimeDep, TenantDep
from app.api.responses import ListEnvelope, ok_list
from app.domains.audit.queries import list_audit_logs
from app.domains.audit.schemas import AuditLogOut

router = APIRouter(tags=["audit"])
MAX_PAGE_SIZE = 100


@router.get("/organizations/{organization_id}/audit-logs", response_model=ListEnvelope[AuditLogOut])
def audit_logs(
    ctx: TenantDep,
    rt: RuntimeDep,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    action: Annotated[str | None, Query(max_length=100)] = None,
    actor_user_id: uuid.UUID | None = None,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    result: Literal["success", "denied", "failed"] | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> ListEnvelope[AuditLogOut]:
    items, total = list_audit_logs(
        rt,
        ctx,
        page=page,
        page_size=page_size,
        action=action,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        result=result,
        created_from=created_from,
        created_to=created_to,
    )
    return ok_list(items, page=page, page_size=page_size, total=total)
