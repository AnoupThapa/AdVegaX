"""Read access to the audit log (Owners and Admins; API §18)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select

from app.domains.audit.models import AuditLog
from app.domains.audit.schemas import AuditLogOut
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.tenancy import TenantContext
from app.runtime import Runtime


def list_audit_logs(
    rt: Runtime,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    action: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    result: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> tuple[list[AuditLogOut], int]:
    authorize(ctx, Permission.AUDIT_VIEW)
    conditions = [AuditLog.organization_id == ctx.organization_id]
    if action:
        conditions.append(AuditLog.action == action)
    if actor_user_id:
        conditions.append(AuditLog.actor_user_id == actor_user_id)
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if result:
        conditions.append(AuditLog.result == result)
    if created_from:
        conditions.append(AuditLog.created_at >= created_from)
    if created_to:
        conditions.append(AuditLog.created_at < created_to)
    with rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
        total = int(
            session.execute(
                select(func.count()).select_from(AuditLog).where(*conditions)
            ).scalar_one()
        )
        rows = (
            session.execute(
                select(AuditLog)
                .where(*conditions)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        items = [
            AuditLogOut(
                id=r.id,
                actor_type=r.actor_type,
                actor_user_id=r.actor_user_id,
                action=r.action,
                resource_type=r.resource_type,
                resource_id=r.resource_id,
                result=r.result,
                correlation_id=r.correlation_id,
                before=r.before_json,
                after=r.after_json,
                metadata=r.metadata_json,
                created_at=r.created_at,
            )
            for r in rows
        ]
    return items, total
