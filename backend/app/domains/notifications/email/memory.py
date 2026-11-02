"""In-memory sender for automated tests (never allowed in deployed environments)."""

from __future__ import annotations

import threading
import uuid

from app.domains.notifications.email.port import EmailMessage, EmailSendError

_lock = threading.Lock()
SENT: list[EmailMessage] = []
FAIL_NEXT: list[bool] = []


class MemorySender:
    def send(self, message: EmailMessage) -> str | None:
        with _lock:
            if FAIL_NEXT:
                FAIL_NEXT.pop(0)
                raise EmailSendError("simulated failure")
            SENT.append(message)
        return f"memory-{uuid.uuid4()}"


def reset() -> None:
    with _lock:
        SENT.clear()
        FAIL_NEXT.clear()
