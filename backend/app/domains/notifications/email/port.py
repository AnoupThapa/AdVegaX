"""Vendor-neutral email sending port (A9)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmailMessage:
    sender: str
    recipient: str
    subject: str
    text: str
    html: str


class EmailSendError(Exception):
    """Delivery failed; the message may be retried."""


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> str | None:
        """Send the message; return a provider message ID when available."""
        ...
