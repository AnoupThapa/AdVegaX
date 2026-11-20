"""SMTP adapter behaviour without a network (smtplib is replaced)."""

from __future__ import annotations

import smtplib

import pytest
from app.core.settings import Settings
from app.domains.notifications.email.port import EmailMessage, EmailSendError
from app.domains.notifications.email.smtp import SmtpSender

MESSAGE = EmailMessage(
    sender="AdVegaX <no-reply@example.com>",
    recipient="to@example.com",
    subject="Hi",
    text="Body",
    html="<p>Body</p>",
)


class FakeSMTP:
    instances: list[FakeSMTP] = []  # noqa: RUF012 - reset per test by the fixture

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, message):
        self.calls.append(("send", message["To"], message["Subject"]))


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)


def test_plain_smtp():
    message_id = SmtpSender(Settings(SMTP_HOST="mail", SMTP_PORT=1025)).send(MESSAGE)
    assert message_id and message_id.startswith("<")
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("mail", 1025)
    assert smtp.calls == [("send", "to@example.com", "Hi")]


def test_starttls_and_login():
    settings = Settings(SMTP_STARTTLS=True, SMTP_USERNAME="user", SMTP_PASSWORD="secret")
    SmtpSender(settings).send(MESSAGE)
    assert FakeSMTP.instances[0].calls[:2] == ["starttls", ("login", "user", "secret")]


def test_ssl():
    SmtpSender(Settings(SMTP_USE_SSL=True, SMTP_PORT=465)).send(MESSAGE)
    assert FakeSMTP.instances[0].port == 465


def test_failures_become_send_errors(monkeypatch):
    def refuse(*_a, **_k):
        raise ConnectionRefusedError()

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    with pytest.raises(EmailSendError, match="ConnectionRefusedError"):
        SmtpSender(Settings()).send(MESSAGE)
