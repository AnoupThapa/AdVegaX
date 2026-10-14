"""Process-wide services shared by the API and workers (built once per process)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import redis

from app.core.clock import Clock, SystemClock
from app.core.security.encryption import EnvelopeCipher, cipher_from_settings
from app.core.security.throttle import Throttler
from app.core.settings import EmailBackend, Settings
from app.db.session import Database
from app.domains.notifications.email.memory import MemorySender
from app.domains.notifications.email.port import EmailSender
from app.domains.notifications.email.smtp import SmtpSender
from app.domains.notifications.service import NotificationService
from app.providers.base.registry import ProviderRegistry, build_registry
from app.providers.http.client import OutboundPolicy
from app.providers.http.ratelimit import ProviderRateLimiter


def build_sender(settings: Settings) -> EmailSender:
    if settings.EMAIL_BACKEND is EmailBackend.MEMORY:
        return MemorySender()
    return SmtpSender(settings)


def celery_enqueue(outbox_id: uuid.UUID) -> None:
    from app.workers.email_tasks import deliver_email

    deliver_email.delay(str(outbox_id))


def celery_enqueue_job(job_id: uuid.UUID, countdown_seconds: int = 0) -> None:
    from app.workers.job_tasks import run_job_task

    run_job_task.apply_async(args=[str(job_id)], countdown=countdown_seconds)


def outbound_policy(settings: Settings) -> OutboundPolicy:
    return OutboundPolicy(
        connect_timeout=settings.OUTBOUND_CONNECT_TIMEOUT.total_seconds(),
        read_timeout=settings.OUTBOUND_READ_TIMEOUT.total_seconds(),
        max_response_bytes=settings.OUTBOUND_MAX_RESPONSE_BYTES,
        max_redirects=settings.OUTBOUND_MAX_REDIRECTS,
        request_timeout=settings.OUTBOUND_REQUEST_TIMEOUT.total_seconds(),
        max_download_bytes=settings.OUTBOUND_MAX_DOWNLOAD_BYTES,
        download_timeout=settings.OUTBOUND_DOWNLOAD_TIMEOUT.total_seconds(),
    )


@dataclass
class Runtime:
    settings: Settings
    db: Database
    redis: redis.Redis
    clock: Clock
    throttler: Throttler
    notifications: NotificationService
    sender: EmailSender
    cipher: EnvelopeCipher
    providers: ProviderRegistry
    rate_limiter: ProviderRateLimiter
    enqueue_job: Callable[[uuid.UUID, int], None]
    extras: dict[str, object] = field(default_factory=dict)

    def cipher_active_version(self) -> int:
        return self.settings.ENCRYPTION_ACTIVE_KEY_VERSION

    def close(self) -> None:
        self.db.dispose()
        self.redis.close()


def build_runtime(
    settings: Settings,
    *,
    clock: Clock | None = None,
    enqueue: Callable[[uuid.UUID], None] = celery_enqueue,
    enqueue_job: Callable[[uuid.UUID, int], None] = celery_enqueue_job,
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
        cipher=cipher_from_settings(
            settings.ENCRYPTION_KEYS.get_secret_value(), settings.ENCRYPTION_ACTIVE_KEY_VERSION
        ),
        providers=build_registry(settings, clock=clock, outbound=outbound_policy(settings)),
        rate_limiter=ProviderRateLimiter(client, clock),
        enqueue_job=enqueue_job,
    )
