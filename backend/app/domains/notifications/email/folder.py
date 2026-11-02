"""Emails written to a folder instead of sent (Phase 16: the desktop installation).

Each message becomes one ``.txt`` file in ``EMAIL_FOLDER`` (sign-up links, invitations,
password resets), so AdVegaX runs on a computer with no email server. Refused when deployed
(deployed environments must use SMTP).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.domains.notifications.email.port import EmailMessage


class FolderSender:
    def __init__(self, folder: str) -> None:
        self._folder = Path(folder)

    def send(self, message: EmailMessage) -> str | None:
        self._folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        who = re.sub(r"[^a-zA-Z0-9@._-]", "_", message.recipient)
        path = self._folder / f"{stamp}-{who}-{uuid.uuid4().hex[:6]}.txt"
        path.write_text(
            f"To: {message.recipient}\nSubject: {message.subject}\n\n{message.text}\n",
            encoding="utf-8",
        )
        return f"folder-{path.name}"
