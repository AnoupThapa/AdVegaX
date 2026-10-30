"""Which store an ad account or analytics property belongs to (Phase 6, 6-02, Q-6-1).

With one store, every ad account and property counts for it — nothing to set. With several, an
owner or admin can assign each one to a store, or leave it for the whole organization (None).
The store must belong to the same organization (also enforced by the composite foreign key).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.domains.audit.service import Actor, record_audit
from app.domains.commerce.models import Store
from app.domains.organizations.tenancy import TenantContext


def assign_store(
    session: Session,
    ctx: TenantContext,
    item: Any,
    store_id: uuid.UUID | None,
    *,
    resource_type: str,
) -> None:
    """Set ``item.store_id`` (an ``AdAccount`` or ``AnalyticsProperty``) and audit the change."""
    if store_id is not None:
        found = session.execute(
            select(Store.id).where(
                Store.organization_id == ctx.organization_id, Store.id == store_id
            )
        ).first()
        if found is None:
            raise ValidationFailed(details=[{"field": "store_id", "issue": "unknown_store"}])
    before = item.store_id
    if before == store_id:
        return
    item.store_id = store_id
    session.flush()
    record_audit(
        session,
        organization_id=ctx.organization_id,
        actor=Actor.user(ctx.user_id),
        action=f"{resource_type}.store_assigned",
        resource_type=resource_type,
        resource_id=item.id,
        before={"store_id": str(before) if before else None},
        after={"store_id": str(store_id) if store_id else None},
    )
