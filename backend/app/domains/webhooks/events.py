"""Small helpers over the system-only webhook intake log (used by intake and by the jobs that
act on recorded events). Only the system role can read or write ``webhook_events``."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import update

from app.domains.webhooks.models import WebhookEvent
from app.runtime import Runtime


@dataclass(frozen=True)
class EventView:
    id: uuid.UUID
    provider: str
    topic: str
    account_id: str
    object_external_id: str | None
    organization_id: uuid.UUID | None
    status: str
    received_at: datetime


def load_event(rt: Runtime, event_id: uuid.UUID) -> EventView | None:
    with rt.db.transaction(system=True) as session:
        event = session.get(WebhookEvent, event_id)
        if event is None:
            return None
        return EventView(
            id=event.id,
            provider=event.provider,
            topic=event.topic,
            account_id=event.external_account_id,
            object_external_id=event.object_external_id,
            organization_id=event.organization_id,
            status=event.status,
            received_at=event.received_at,
        )


def finish_event(
    rt: Runtime,
    event_id: uuid.UUID,
    status: str,
    error: str | None = None,
    *,
    clear_object: bool = False,
) -> None:
    """Record the outcome. ``clear_object`` drops the object id once it is no longer needed
    (e.g. a customer id after a privacy request was carried out — data minimization)."""
    values: dict[str, object] = {
        "status": status,
        "processed_at": rt.clock.now(),
        "error_code": error[:64] if error else None,
    }
    if clear_object:
        values["object_external_id"] = None
    with rt.db.transaction(system=True) as session:
        session.execute(update(WebhookEvent).where(WebhookEvent.id == event_id).values(**values))
