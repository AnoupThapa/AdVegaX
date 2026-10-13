"""Job handlers for connections and resources. They run in the worker under tenant context."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import String, select

from app.domains.audit.service import Actor, record_audit
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalConnectionCredential,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.integrations.tokens import usable_secrets
from app.domains.jobs.models import JobRun
from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError, create_job
from app.providers.base.errors import AuthExpiredError, PermissionDeniedError, ProviderError
from app.providers.base.interfaces import PlatformProvider
from app.providers.base.types import ResourceDescriptor, ResourceKind
from app.runtime import Runtime

WORKER = Actor("worker", None)


def mark_connection_error(
    rt: Runtime, org_id: uuid.UUID, connection_id: uuid.UUID, exc: ProviderError
) -> None:
    status = "expired" if isinstance(exc, AuthExpiredError) else "error"
    with rt.db.transaction(org_id=org_id) as session:
        connection = session.get(ExternalConnection, connection_id)
        if connection is not None and connection.status == "active":
            connection.status, connection.last_error_code = status, exc.code
            connection.last_error_at = rt.clock.now()
            record_audit(
                session,
                organization_id=org_id,
                actor=WORKER,
                action="connection.health_changed",
                resource_type="connection",
                resource_id=connection_id,
                after={"status": status, "error": exc.code},
            )


def call_provider[T](
    rt: Runtime,
    provider: PlatformProvider,
    org_id: uuid.UUID,
    connection_id: uuid.UUID,
    fn: Callable[[], T],
) -> T:
    """Rate-limited provider call; auth failures mark the connection's health."""
    rate, burst = provider.rate_limit
    rt.rate_limiter.acquire(f"{provider.code}:{connection_id}", rate_per_second=rate, burst=burst)
    try:
        return fn()
    except (AuthExpiredError, PermissionDeniedError) as exc:
        mark_connection_error(rt, org_id, connection_id, exc)
        raise


def discover(rt: Runtime, job: ClaimedJob) -> None:
    org_id = job.organization_id
    if org_id is None or job.subject_id is None:
        raise JobSubjectGoneError()
    connection_id = uuid.UUID(job.subject_id)
    with rt.db.transaction(org_id=org_id) as session:
        connection = session.execute(
            select(ExternalConnection).where(
                ExternalConnection.id == connection_id, ExternalConnection.organization_id == org_id
            )
        ).scalar_one_or_none()
        if connection is None or connection.status != "active":
            raise JobSubjectGoneError()
        provider = rt.providers.get(connection.provider)
    secrets = usable_secrets(rt, org_id, connection_id)
    descriptors = call_provider(
        rt, provider, org_id, connection_id, lambda: provider.discover_resources(secrets)
    )
    now = rt.clock.now()
    seen: set[tuple[str, str]] = set()
    with rt.db.transaction(org_id=org_id) as session:
        existing = {
            (r.kind, r.external_id): r
            for r in session.execute(
                select(ExternalResource)
                .where(ExternalResource.connection_id == connection_id)
                .with_for_update()
            ).scalars()
        }
        added = 0
        for d in descriptors:
            key = (ResourceKind(d.kind).value, d.external_id)
            seen.add(key)
            row = existing.get(key)
            if row is None:
                session.add(
                    ExternalResource(
                        organization_id=org_id,
                        connection_id=connection_id,
                        kind=key[0],
                        provider=provider.code,
                        external_id=d.external_id,
                        display_name=d.display_name,
                        currency=d.currency,
                        timezone=d.timezone,
                        accessible=True,
                        capabilities=provider.capabilities.as_dict(),
                        discovered_at=now,
                        last_seen_at=now,
                    )
                )
                added += 1
            else:
                row.display_name, row.currency, row.timezone = (
                    d.display_name,
                    d.currency,
                    d.timezone,
                )
                row.accessible, row.last_seen_at = True, now
                row.capabilities = provider.capabilities.as_dict()
        lost = [r for key, r in existing.items() if key not in seen and r.accessible]
        ended = 0
        for row in lost:
            row.accessible = False
            for link in session.execute(
                select(OrganizationResourceLink)
                .where(
                    OrganizationResourceLink.external_resource_id == row.id,
                    OrganizationResourceLink.status == "active",
                )
                .with_for_update()
            ).scalars():
                link.status, link.unlinked_at, link.unlink_reason = (
                    "unlinked",
                    now,
                    "resource_inaccessible",
                )
                ended += 1
        connection = session.get(ExternalConnection, connection_id)
        if connection is not None:
            connection.last_error_code, connection.last_error_at = None, None
        record_audit(
            session,
            organization_id=org_id,
            actor=WORKER,
            action="connection.discovered",
            resource_type="connection",
            resource_id=connection_id,
            metadata={
                "resources_found": len(descriptors),
                "added": added,
                "now_inaccessible": len(lost),
                "links_ended": ended,
                "job_id": str(job.id),
            },
        )


def sync(rt: Runtime, job: ClaimedJob) -> None:
    org_id = job.organization_id
    if org_id is None or job.subject_id is None:
        raise JobSubjectGoneError()
    resource_id = uuid.UUID(job.subject_id)
    with rt.db.transaction(org_id=org_id) as session:
        row = session.execute(
            select(ExternalResource, ExternalConnection)
            .join(ExternalConnection, ExternalConnection.id == ExternalResource.connection_id)
            .join(
                OrganizationResourceLink,
                (OrganizationResourceLink.external_resource_id == ExternalResource.id)
                & (OrganizationResourceLink.status == "active"),
            )
            .where(ExternalResource.id == resource_id, ExternalResource.organization_id == org_id)
        ).one_or_none()
        if row is None or row[1].status != "active":
            raise JobSubjectGoneError()
        resource, connection = row
        provider = rt.providers.get(connection.provider)
        descriptor = ResourceDescriptor(
            ResourceKind(resource.kind),
            resource.external_id,
            resource.display_name,
            resource.currency,
            resource.timezone,
        )
        connection_id = connection.id
        if resource.kind == ResourceKind.STORE.value:
            from app.domains.commerce import importer

            if importer.commerce_provider(provider) is not None:
                # Commerce stores sync through bulk exports: (re)start the import chain.
                store = importer.on_store_linked(
                    session, rt, resource=resource, connection=connection, user_id=None
                )
                if store is not None and store.first_import_completed_at is not None:
                    importer.start_import(session, rt, store, requested_by=job.requested_by_user_id)
                return
    secrets = usable_secrets(rt, org_id, connection_id)
    summary = call_provider(
        rt, provider, org_id, connection_id, lambda: provider.sync_resource(secrets, descriptor)
    )
    with rt.db.transaction(org_id=org_id) as session:
        current = session.get(ExternalResource, resource_id)
        if current is not None:
            current.last_synced_at = rt.clock.now()
        record_audit(
            session,
            organization_id=org_id,
            actor=WORKER,
            action="resource.synced",
            resource_type="external_resource",
            resource_id=resource_id,
            metadata={"items": summary.items_synchronized, "job_id": str(job.id)},
        )


def refresh_credentials(rt: Runtime, job: ClaimedJob) -> None:
    """Keep-alive refresh (scheduled): rotating refresh tokens never reach their expiry."""
    org_id = job.organization_id
    if org_id is None or job.subject_id is None:
        raise JobSubjectGoneError()
    connection_id = uuid.UUID(job.subject_id)
    with rt.db.transaction(org_id=org_id) as session:
        connection = session.get(ExternalConnection, connection_id)
        if connection is None or connection.status != "active":
            raise JobSubjectGoneError()
    usable_secrets(rt, org_id, connection_id, force=True)


JOB_REFRESH = "connection.refresh_credentials"


def enqueue_keepalive_refreshes(rt: Runtime) -> int:
    """Scheduled sweep: queue a refresh for every live connection whose rotating refresh token
    has not been used within ``TOKEN_KEEPALIVE_INTERVAL`` (so it never reaches its expiry).

    The candidate list is read with the system role (ids only — no secrets are decrypted
    here); each job is created inside its own organization's tenant context.
    """
    cutoff = rt.clock.now() - rt.settings.TOKEN_KEEPALIVE_INTERVAL
    with rt.db.transaction(system=True) as session:
        pending = select(JobRun.subject_id).where(
            JobRun.job_type == JOB_REFRESH, JobRun.status.in_(("queued", "running"))
        )
        candidates = session.execute(
            select(ExternalConnection.id, ExternalConnection.organization_id)
            .join(
                ExternalConnectionCredential,
                ExternalConnectionCredential.connection_id == ExternalConnection.id,
            )
            .where(
                ExternalConnection.status == "active",
                ExternalConnectionCredential.ciphertext.is_not(None),
                ExternalConnectionCredential.refresh_expires_at.is_not(None),
                (ExternalConnectionCredential.last_refreshed_at.is_(None))
                | (ExternalConnectionCredential.last_refreshed_at < cutoff),
                ExternalConnection.id.cast(String).not_in(pending),
            )
        ).all()
    for connection_id, org_id in candidates:
        with rt.db.transaction(org_id=org_id) as session:
            create_job(
                session,
                rt,
                organization_id=org_id,
                job_type=JOB_REFRESH,
                subject_type="connection",
                subject_id=connection_id,
                requested_by=None,
            )
    return len(candidates)
