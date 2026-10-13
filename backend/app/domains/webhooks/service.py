"""Generic webhook intake (task 2A-05, PHASE_02A_PLAN §7).

Flow for every delivery, before anything is stored:

1. per-IP rate limit;
2. the provider verifies the signature over the **raw** body (401 if it fails) and returns
   metadata only — the payload never leaves the provider module (Q8);
3. a delivery triggered too long ago (or in the future) is refused as a possible replay;
4. the metadata is inserted into ``webhook_events``; the unique webhook id makes a redelivery a
   no-op, so each delivery is acted on once;
5. the platform account is mapped to its organization with a narrow system-role lookup, and any
   follow-up work runs as a tenant job — the response goes back well within Shopify's 5 s.

What happens per kind in this task: an uninstall revokes the connection (job below); privacy
requests are recorded and audited; "object changed" signals are recorded. Fetching changed
objects and carrying out privacy requests are task 2A-07.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from enum import StrEnum

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import InvalidWebhook, InvalidWebhookSignature, NotFound
from app.core.security.throttle import Limit
from app.domains.audit.service import Actor, record_audit
from app.domains.commerce.models import Store
from app.domains.integrations.models import ExternalConnection
from app.domains.integrations.service import revoke_by_platform
from app.domains.jobs.service import ClaimedJob, JobSubjectGoneError, create_job
from app.domains.webhooks.models import WebhookEvent
from app.providers.base.capabilities import Capability
from app.providers.base.errors import InvalidRequestError, InvalidSignatureError
from app.providers.base.types import PRIVACY_KINDS, WebhookDelivery, WebhookKind
from app.runtime import Runtime

logger = logging.getLogger("advegax.webhooks")

JOB_PLATFORM_REVOKED = "connection.platform_revoked"
SYSTEM = Actor("system", None)
MINUTE = 60


class Outcome(StrEnum):
    ACCEPTED = "accepted"  # recorded; follow-up work queued or pending (2A-07)
    DUPLICATE = "duplicate"  # same webhook id seen before: nothing done again
    IGNORED = "ignored"  # verified, recorded, but nothing to do (unknown store, unhandled topic)


def _owner(session: Session, provider: str, account_id: str) -> uuid.UUID | None:
    """Organization for a platform account: the live connection, else the imported store
    (privacy requests such as ``shop/redact`` arrive after the connection was revoked)."""
    org = session.execute(
        select(ExternalConnection.organization_id)
        .where(
            ExternalConnection.provider == provider,
            ExternalConnection.external_account_id == account_id,
            ExternalConnection.status != "revoked",
        )
        .limit(1)
    ).scalar_one_or_none()
    if org is not None:
        return org
    return session.execute(
        select(Store.organization_id)
        .where(Store.provider == provider, Store.domain == account_id)
        .order_by(Store.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _initial_status(delivery: WebhookDelivery, org_id: uuid.UUID | None) -> str:
    if org_id is None or delivery.kind is WebhookKind.UNHANDLED:
        return "ignored"
    return "received"


def _check_freshness(rt: Runtime, delivery: WebhookDelivery) -> None:
    if delivery.triggered_at is None:
        return
    age = rt.clock.now() - delivery.triggered_at
    if age > rt.settings.WEBHOOK_MAX_AGE or -age > rt.settings.WEBHOOK_CLOCK_SKEW:
        raise InvalidWebhookSignature()


def receive(
    rt: Runtime, provider_code: str, headers: Mapping[str, str], body: bytes, *, ip: str
) -> Outcome:
    rt.throttler.hit(
        Limit("webhook_ip", rt.settings.THROTTLE_WEBHOOK_PER_IP_PER_MINUTE, MINUTE), ip
    )
    provider = rt.providers.get(provider_code)
    if not provider.capabilities.supports(Capability.WEBHOOKS):
        raise NotFound()
    try:
        delivery = provider.parse_webhook(headers, body)
    except InvalidSignatureError:
        logger.warning("webhook_signature_invalid", extra={"provider": provider_code})
        raise InvalidWebhookSignature() from None
    except InvalidRequestError as exc:
        logger.warning("webhook_invalid", extra={"provider": provider_code, "error": exc.code})
        raise InvalidWebhook() from None
    _check_freshness(rt, delivery)

    now = rt.clock.now()
    with rt.db.transaction(system=True) as session:
        org_id = _owner(session, provider_code, delivery.account_id)
        status = _initial_status(delivery, org_id)
        event_id = session.execute(
            insert(WebhookEvent)
            .values(
                provider=provider_code,
                webhook_id=delivery.webhook_id,
                topic=delivery.topic,
                external_account_id=delivery.account_id,
                object_external_id=delivery.object_external_id,
                object_updated_at=delivery.object_updated_at,
                triggered_at=delivery.triggered_at,
                received_at=now,
                organization_id=org_id,
                status=status,
                processed_at=now if status == "ignored" else None,
            )
            .on_conflict_do_nothing(constraint="uq_webhook_events_provider_webhook_id")
            .returning(WebhookEvent.id)
        ).scalar_one_or_none()
    log = {"provider": provider_code, "topic": delivery.topic, "webhook_id": delivery.webhook_id}
    if event_id is None:
        logger.info("webhook_duplicate", extra=log)
        return Outcome.DUPLICATE
    logger.info("webhook_received", extra={**log, "status": status})
    if org_id is None or status == "ignored":
        return Outcome.IGNORED

    try:
        _follow_up(rt, org_id, event_id, delivery)
    except Exception:
        # Undo the record so the platform's retry is processed afresh rather than being
        # mistaken for an already-handled duplicate.
        with rt.db.transaction(system=True) as session:
            session.execute(delete(WebhookEvent).where(WebhookEvent.id == event_id))
        raise
    return Outcome.ACCEPTED


def _follow_up(
    rt: Runtime, org_id: uuid.UUID, event_id: uuid.UUID, delivery: WebhookDelivery
) -> None:
    if delivery.kind is WebhookKind.APP_UNINSTALLED:
        with rt.db.transaction(org_id=org_id) as session:
            create_job(
                session,
                rt,
                organization_id=org_id,
                job_type=JOB_PLATFORM_REVOKED,
                subject_type="webhook_event",
                subject_id=event_id,
                requested_by=None,
            )
    elif delivery.kind in PRIVACY_KINDS:
        # Recorded and audited now; carried out by task 2A-07 (Shopify allows 30 days).
        with rt.db.transaction(org_id=org_id) as session:
            record_audit(
                session,
                organization_id=org_id,
                actor=SYSTEM,
                action="privacy.request_received",
                resource_type="webhook_event",
                resource_id=event_id,
                metadata={"topic": delivery.topic, "kind": delivery.kind.value},
            )


# ------------------------------------------------------------------ job handlers
def _finish(rt: Runtime, event_id: uuid.UUID, status: str, error: str | None = None) -> None:
    with rt.db.transaction(system=True) as session:
        session.execute(
            update(WebhookEvent)
            .where(WebhookEvent.id == event_id)
            .values(status=status, processed_at=rt.clock.now(), error_code=error)
        )


def platform_revoked(rt: Runtime, job: ClaimedJob) -> None:
    """``app/uninstalled``: AdVegaX's access to the store has ended. Delete its tokens, mark
    the connection revoked, end its links; keep imported data (D-2A-2)."""
    if job.subject_id is None or job.organization_id is None:
        raise JobSubjectGoneError()
    event_id = uuid.UUID(job.subject_id)
    with rt.db.transaction(system=True) as session:
        event = session.get(WebhookEvent, event_id)
        if event is None or event.organization_id != job.organization_id:
            raise JobSubjectGoneError()
        if event.status != "received":
            return  # already handled
        provider, account = event.provider, event.external_account_id
    revoke_by_platform(
        rt, provider, account, reason="app_uninstalled", organization_id=job.organization_id
    )
    _finish(rt, event_id, "processed")


def purge_expired(rt: Runtime) -> int:
    """Delete intake metadata older than ``WEBHOOK_RETENTION`` (PHASE_02A_PLAN §9)."""
    cutoff = rt.clock.now() - rt.settings.WEBHOOK_RETENTION
    with rt.db.transaction(system=True) as session:
        result = session.execute(delete(WebhookEvent).where(WebhookEvent.received_at < cutoff))
    return int(getattr(result, "rowcount", 0) or 0)
