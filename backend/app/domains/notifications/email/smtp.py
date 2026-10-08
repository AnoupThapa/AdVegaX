"""SMTP adapter. Works with local mail catchers and most transactional email providers."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage as MimeMessage
from email.utils import make_msgid

from app.core.settings import Settings
from app.domains.notifications.email.port import EmailMessage, EmailSendError


class SmtpSender:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def send(self, message: EmailMessage) -> str | None:
        mime = MimeMessage()
        message_id = make_msgid(domain="advegax")
        mime["From"] = message.sender
        mime["To"] = message.recipient
        mime["Subject"] = message.subject
        mime["Message-ID"] = message_id
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        s = self._s
        try:
            smtp: smtplib.SMTP
            if s.SMTP_USE_SSL:
                smtp = smtplib.SMTP_SSL(
                    s.SMTP_HOST,
                    s.SMTP_PORT,
                    timeout=s.SMTP_TIMEOUT_SECONDS,
                    context=ssl.create_default_context(),
                )
            else:
                smtp = smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT, timeout=s.SMTP_TIMEOUT_SECONDS)
            with smtp:
                if s.SMTP_STARTTLS and not s.SMTP_USE_SSL:
                    smtp.starttls(context=ssl.create_default_context())
                if s.SMTP_USERNAME and s.SMTP_PASSWORD:
                    smtp.login(s.SMTP_USERNAME, s.SMTP_PASSWORD.get_secret_value())
                smtp.send_message(mime)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailSendError(type(exc).__name__) from exc
        return message_id
