"""Data retention (Phase 15, task 15-01, PHASE_15_PLAN Q-15-3; A34).

A store, ad account or analytics property that has been **unlinked** from its organization for
longer than ``DATA_RETENTION_AFTER_REMOVAL`` (90 days), and not linked again, is deleted with
everything imported for it (the database's cascades). Audit logs are not touched (kept 7
years, Q-15-3). Each deletion is audited in the organization. Off unless ``RETENTION_ENABLED``.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete, func, select

from app.domains.audit.service import Actor, record_audit
from app.domains.integrations.models import ExternalResource, OrganizationResourceLink
from app.runtime import Runtime

logger = logging.getLogger("advegax.retention")
SYSTEM = Actor("system", None)


def due(rt: Runtime) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(organization, resource) pairs past their retention, from the system role's narrow read."""
    cutoff = rt.clock.now() - rt.settings.DATA_RETENTION_AFTER_REMOVAL
    link = OrganizationResourceLink
    with rt.db.transaction(system=True) as session:
        rows = session.execute(
            select(link.organization_id, link.external_resource_id)
            .group_by(link.organization_id, link.external_resource_id)
            .having(
                func.count().filter(link.status == "active") == 0,
                func.max(link.unlinked_at) < cutoff,
            )
            .order_by(link.organization_id, link.external_resource_id)
        ).all()
    return [(r[0], r[1]) for r in rows]


def purge(rt: Runtime) -> int:
    """Delete what is past its retention. Returns how many resources were deleted."""
    if not rt.settings.RETENTION_ENABLED:
        return 0
    deleted = 0
    for org_id, resource_id in due(rt):
        with rt.db.transaction(org_id=org_id) as session:
            resource = session.get(ExternalResource, resource_id)
            if resource is None:
                continue
            active = session.execute(
                select(func.count())
                .select_from(OrganizationResourceLink)
                .where(
                    OrganizationResourceLink.external_resource_id == resource_id,
                    OrganizationResourceLink.status == "active",
                )
            ).scalar_one()
            if active:
                continue  # linked again meanwhile
            before = {"kind": resource.kind, "external_id": resource.external_id}
        # The app role never deletes integration rows (1B); the system role does, here only,
        # and the database's cascades remove what was imported for the resource.
        with rt.db.transaction(system=True) as session:
            session.execute(
                delete(ExternalResource).where(
                    ExternalResource.id == resource_id,
                    ~select(OrganizationResourceLink.external_resource_id)
                    .where(
                        OrganizationResourceLink.external_resource_id == resource_id,
                        OrganizationResourceLink.status == "active",
                    )
                    .exists(),
                )
            )
        with rt.db.transaction(org_id=org_id) as session:
            record_audit(
                session,
                organization_id=org_id,
                actor=SYSTEM,
                action="retention.resource_deleted",
                resource_type="external_resource",
                resource_id=resource_id,
                before=before,
            )
        deleted += 1
    if deleted:
        logger.info("retention_purged", extra={"resources": deleted})
    return deleted
