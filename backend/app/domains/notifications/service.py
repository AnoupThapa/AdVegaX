"""Notifications domain: other domains request templated emails here, never a vendor (A9)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.db.session import after_commit
from app.domains.notifications.models import EmailOutbox
from app.domains.notifications.templates import TEMPLATES

Enqueue = Callable[[uuid.UUID], None]


def humanize(duration: timedelta) -> str:
    seconds = int(duration.total_seconds())
    for unit, size, minimum in (("day", 86400, 2), ("hour", 3600, 1), ("minute", 60, 1)):
        if seconds >= size * minimum and seconds % size == 0:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''}"
    minutes = max(1, seconds // 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


class NotificationService:
    def __init__(self, enqueue: Enqueue) -> None:
        self._enqueue = enqueue

    def send_email(
        self,
        session: Session,
        *,
        template: str,
        recipient: str,
        variables: dict[str, Any],
        organization_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Write to the outbox in the caller's transaction; dispatch after commit."""
        if template not in TEMPLATES:
            raise ValueError(f"Unknown email template: {template}")
        outbox_id = uuid.uuid4()
        session.execute(
            insert(EmailOutbox).values(
                id=outbox_id,
                organization_id=organization_id,
                template=template,
                recipient=recipient,
                payload=variables,
            )
        )
        after_commit(session, lambda: self._enqueue(outbox_id))
        return outbox_id
