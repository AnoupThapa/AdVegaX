"""Outbox delivery, executed by the worker under the advegax_system role."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from sqlalchemy import func, select, text, update

from app.core.settings import Settings
from app.db.session import Database
from app.domains.notifications.email.port import EmailMessage, EmailSender, EmailSendError
from app.domains.notifications.models import EmailOutbox
from app.domains.notifications.templates import render

logger = logging.getLogger("advegax.email")


class DeliveryOutcome(StrEnum):
    SENT = "sent"
    RETRY = "retry"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class DeliveryResult:
    outcome: DeliveryOutcome
    retry_in: timedelta | None = None


def deliver(
    db: Database, settings: Settings, sender: EmailSender, outbox_id: uuid.UUID
) -> DeliveryResult:
    with db.transaction(system=True) as session:
        row = session.execute(
            select(EmailOutbox)
            .where(
                EmailOutbox.id == outbox_id,
                EmailOutbox.status == "pending",
                EmailOutbox.next_attempt_at <= func.now(),
            )
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if row is None:
            return DeliveryResult(DeliveryOutcome.SKIPPED)
        try:
            subject, body_text, body_html = render(row.template, row.payload)
            message_id = sender.send(
                EmailMessage(
                    sender=settings.EMAIL_FROM,
                    recipient=row.recipient,
                    subject=subject,
                    text=body_text,
                    html=body_html,
                )
            )
        except EmailSendError as exc:
            attempts = row.attempts + 1
            if attempts >= settings.EMAIL_MAX_ATTEMPTS:
                session.execute(
                    update(EmailOutbox)
                    .where(EmailOutbox.id == row.id)
                    .values(
                        attempts=attempts,
                        status="failed",
                        last_error=str(exc)[:500],
                        payload={},
                        updated_at=func.now(),
                    )
                )
                logger.error(
                    "email_delivery_failed",
                    extra={"outbox_id": str(row.id), "template": row.template},
                )
                return DeliveryResult(DeliveryOutcome.FAILED)
            delay = settings.EMAIL_RETRY_BASE_DELAY * (2 ** (attempts - 1))
            session.execute(
                update(EmailOutbox)
                .where(EmailOutbox.id == row.id)
                .values(
                    attempts=attempts,
                    last_error=str(exc)[:500],
                    next_attempt_at=func.now()
                    + text(f"interval '{int(delay.total_seconds())} seconds'"),
                    updated_at=func.now(),
                )
            )
            logger.warning(
                "email_delivery_retry", extra={"outbox_id": str(row.id), "attempt": attempts}
            )
            return DeliveryResult(DeliveryOutcome.RETRY, retry_in=delay)
        # Sent: the payload (which may contain single-use links) is removed.
        session.execute(
            update(EmailOutbox)
            .where(EmailOutbox.id == row.id)
            .values(
                status="sent",
                attempts=row.attempts + 1,
                sent_at=func.now(),
                payload={},
                provider_message_id=message_id,
                last_error=None,
                updated_at=func.now(),
            )
        )
        logger.info("email_sent", extra={"outbox_id": str(row.id), "template": row.template})
        return DeliveryResult(DeliveryOutcome.SENT)


def due_outbox_ids(db: Database, limit: int = 100) -> list[uuid.UUID]:
    with db.transaction(system=True) as session:
        return list(
            session.execute(
                select(EmailOutbox.id)
                .where(EmailOutbox.status == "pending", EmailOutbox.next_attempt_at <= func.now())
                .order_by(EmailOutbox.created_at)
                .limit(limit)
            ).scalars()
        )
