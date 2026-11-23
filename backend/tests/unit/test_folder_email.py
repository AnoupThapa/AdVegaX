"""The desktop installation's email folder (Phase 16)."""

from __future__ import annotations

from app.domains.notifications.email.folder import FolderSender
from app.domains.notifications.email.port import EmailMessage


def test_each_email_becomes_a_file(tmp_path):
    sender = FolderSender(str(tmp_path / "mail"))
    message = EmailMessage("AdVegaX <a@b>", "new person@example.com", "Verify", "Link: x", "<p/>")
    assert sender.send(message).startswith("folder-")
    (written,) = (tmp_path / "mail").iterdir()
    assert "new_person@example.com" in written.name
    assert written.read_text(encoding="utf-8").startswith(
        "To: new person@example.com\nSubject: Verify"
    )
