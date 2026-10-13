"""Celery application (Redis broker). Database job records arrive in Phase 1B."""

from __future__ import annotations

from typing import Any

from celery import Celery
from celery.signals import setup_logging

from app.core.logging import configure_logging
from app.core.settings import get_settings

_settings = get_settings()

celery_app = Celery(
    "advegax",
    broker=_settings.REDIS_URL.get_secret_value(),
    include=["app.workers.email_tasks", "app.workers.job_tasks"],
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_always_eager=_settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=True,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "email-sweep": {
            "task": "advegax.schedule.email_sweep",
            "schedule": _settings.SCHEDULE_EMAIL_SWEEP_INTERVAL.total_seconds(),
        },
        "job-recovery": {
            "task": "advegax.schedule.job_recovery",
            "schedule": _settings.SCHEDULE_JOB_RECOVERY_INTERVAL.total_seconds(),
        },
        "token-refresh": {
            "task": "advegax.schedule.token_refresh",
            "schedule": _settings.SCHEDULE_TOKEN_REFRESH_INTERVAL.total_seconds(),
        },
        "webhook-purge": {
            "task": "advegax.schedule.webhook_purge",
            "schedule": _settings.SCHEDULE_WEBHOOK_PURGE_INTERVAL.total_seconds(),
        },
    },
)


@setup_logging.connect  # type: ignore[untyped-decorator]
def _configure_worker_logging(**_: Any) -> None:
    """Workers use the same JSON logging and secret scrubbing as the API."""
    configure_logging(_settings.LOG_LEVEL)
