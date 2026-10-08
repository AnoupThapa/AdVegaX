"""Process-wide services shared by the API and workers (built once per process)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import redis

from app.core.clock import Clock, SystemClock
from app.core.security.throttle import Throttler
from app.core.settings import EmailBackend, Settings
from app.db.session import Database
from app.domains.notifications.email.memory import MemorySender
from app.domains.notifications.email.port import EmailSender
from app.domains.notifications.email.smtp import SmtpSender
from app.domains.notifications.service import NotificationService


def build_sender(settings: Settings) -> EmailSender:
    if settings.EMAIL_BACKEND is EmailBackend.MEMORY:
        return MemorySender()
    return SmtpSender(settings)


def celery_enqueue(outbox_id: uuid.UUID) -> None:
    from app.workers.email_tasks import deliver_email

    deliver_email.delay(str(outbox_id))


@dataclass
class Runtime:
    settings: Settings
    db: Database
    redis: redis.Redis
    clock: Clock
    throttler: Throttler
    notifications: NotificationService
    sender: EmailSender
    extras: dict[str, object] = field(default_factory=dict)

    def close(self) -> None:
        self.db.dispose()
        self.redis.close()


def build_runtime(
    settings: Settings,
    *,
    clock: Clock | None = None,
    enqueue: Callable[[uuid.UUID], None] = celery_enqueue,
) -> Runtime:
    clock = clock or SystemClock()
    client = redis.Redis.from_url(settings.REDIS_URL.get_secret_value(), socket_timeout=2)
    return Runtime(
        settings=settings,
        db=Database(settings),
        redis=client,
        clock=clock,
        throttler=Throttler(client, clock, fail_open=settings.THROTTLE_FAIL_OPEN),
        notifications=NotificationService(enqueue),
        sender=build_sender(settings),
    )
