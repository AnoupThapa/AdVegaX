"""Outbox delivery: success, retry with backoff, permanent failure, payload redaction."""

from __future__ import annotations

import uuid

from app.domains.notifications.delivery import DeliveryOutcome, deliver
from app.domains.notifications.email import memory
from app.workers import email_tasks
from sqlalchemy import text


def _outbox(admin_engine):
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT template, status, attempts, payload, provider_message_id, last_error "
                "FROM email_outbox ORDER BY created_at"
            )
        ).all()


def test_sent_email_redacts_payload(client, admin_engine):
    client.register("w@example.com")
    rows = _outbox(admin_engine)
    assert len(rows) == 1
    template, status, attempts, payload, provider_id, _ = rows[0]
    assert (template, status, attempts, payload) == ("email_verification", "sent", 1, {})
    assert provider_id.startswith("memory-")
    assert len(memory.SENT) == 1


def test_retry_then_permanent_failure(client, admin_engine, settings, runtime):
    memory.FAIL_NEXT.extend([True] * settings.EMAIL_MAX_ATTEMPTS)
    client.register("f@example.com")
    _, status, attempts, payload, _, last_error = _outbox(admin_engine)[0]
    assert (status, attempts) == ("pending", 1)
    assert payload  # kept for the retry
    assert last_error == "simulated failure"
    outbox_id = _id(admin_engine)
    for _ in range(settings.EMAIL_MAX_ATTEMPTS - 1):
        _make_due(admin_engine)
        deliver(runtime.db, settings, runtime.sender, outbox_id)
    _, status, attempts, payload, _, _ = _outbox(admin_engine)[0]
    assert (status, attempts, payload) == ("failed", settings.EMAIL_MAX_ATTEMPTS, {})
    assert (
        deliver(runtime.db, settings, runtime.sender, outbox_id).outcome is DeliveryOutcome.SKIPPED
    )


def test_retry_then_success_and_sweep(client, admin_engine, settings):
    memory.FAIL_NEXT.append(True)
    client.register("s@example.com")
    assert _outbox(admin_engine)[0][1] == "pending"
    assert email_tasks.deliver_pending() == 0  # not due yet (backoff)
    _make_due(admin_engine)
    assert email_tasks.deliver_pending() == 1
    assert _outbox(admin_engine)[0][1:3] == ("sent", 2)


def test_unknown_outbox_id_is_skipped(runtime, settings):
    result = deliver(runtime.db, settings, runtime.sender, uuid.uuid4())
    assert result.outcome is DeliveryOutcome.SKIPPED


def test_celery_task_entry_point(client, admin_engine):
    memory.FAIL_NEXT.append(True)
    client.register("t@example.com")
    _make_due(admin_engine)
    assert email_tasks.deliver_email(str(_id(admin_engine))) == "sent"


def _id(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT id FROM email_outbox")).scalar_one()


def _make_due(engine):
    with engine.begin() as conn:
        conn.execute(text("UPDATE email_outbox SET next_attempt_at = now() - interval '1 second'"))
