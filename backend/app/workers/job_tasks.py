"""Celery entry points for durable jobs and scheduled maintenance (PHASE_01B_PLAN §11)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping

import redis

from app.domains.advertising import importer as ad_importer
from app.domains.commerce import importer, incremental, privacy
from app.domains.integrations import jobs as integration_jobs
from app.domains.integrations.service import JOB_DISCOVER, JOB_SYNC
from app.domains.jobs.service import Handler, JobOutcome, recover_stuck_jobs, run_job
from app.domains.webhooks import service as webhooks
from app.workers.celery_app import celery_app
from app.workers.email_tasks import deliver_pending, worker_runtime

HANDLERS: Mapping[str, Handler] = {
    JOB_DISCOVER: integration_jobs.discover,
    JOB_SYNC: integration_jobs.sync,
    integration_jobs.JOB_REFRESH: integration_jobs.refresh_credentials,
    webhooks.JOB_PLATFORM_REVOKED: webhooks.platform_revoked,
    importer.JOB_IMPORT_STEP: importer.import_step,
    ad_importer.JOB_AD_IMPORT_STEP: ad_importer.import_step,
    incremental.JOB_OBJECT_CHANGED: incremental.object_changed,
    privacy.JOB_CUSTOMER_DATA_REQUEST: privacy.customer_data_request,
    privacy.JOB_CUSTOMER_REDACT: privacy.customer_redact,
    privacy.JOB_SHOP_REDACT: privacy.shop_redact,
}


def run_job_now(job_id: uuid.UUID) -> JobOutcome:
    return run_job(worker_runtime(), job_id, HANDLERS)


@celery_app.task(name="advegax.jobs.run")  # type: ignore[untyped-decorator]
def run_job_task(job_id: str) -> str:
    return run_job_now(uuid.UUID(job_id)).value


def run_singleton(
    client: redis.Redis, name: str, ttl_seconds: int, fn: Callable[[], int]
) -> int | None:
    """Run ``fn`` only if no other scheduler instance ran it within ``ttl_seconds``.

    Guarantees a single active run per schedule tick even if two schedulers are deployed.
    """
    if not client.set(f"schedule-lock:{name}", "1", nx=True, ex=max(1, ttl_seconds)):
        return None
    return fn()


@celery_app.task(name="advegax.schedule.email_sweep")  # type: ignore[untyped-decorator]
def email_sweep_task() -> int | None:
    rt = worker_runtime()
    ttl = int(rt.settings.SCHEDULE_EMAIL_SWEEP_INTERVAL.total_seconds() * 0.9)
    return run_singleton(rt.redis, "email_sweep", ttl, deliver_pending)


@celery_app.task(name="advegax.schedule.job_recovery")  # type: ignore[untyped-decorator]
def job_recovery_task() -> int | None:
    rt = worker_runtime()
    ttl = int(rt.settings.SCHEDULE_JOB_RECOVERY_INTERVAL.total_seconds() * 0.9)
    return run_singleton(rt.redis, "job_recovery", ttl, lambda: recover_stuck_jobs(rt))


@celery_app.task(name="advegax.schedule.token_refresh")  # type: ignore[untyped-decorator]
def token_refresh_task() -> int | None:
    rt = worker_runtime()
    ttl = int(rt.settings.SCHEDULE_TOKEN_REFRESH_INTERVAL.total_seconds() * 0.9)
    return run_singleton(
        rt.redis, "token_refresh", ttl, lambda: integration_jobs.enqueue_keepalive_refreshes(rt)
    )


@celery_app.task(name="advegax.schedule.webhook_purge")  # type: ignore[untyped-decorator]
def webhook_purge_task() -> int | None:
    rt = worker_runtime()
    ttl = int(rt.settings.SCHEDULE_WEBHOOK_PURGE_INTERVAL.total_seconds() * 0.9)
    return run_singleton(rt.redis, "webhook_purge", ttl, lambda: webhooks.purge_expired(rt))


@celery_app.task(name="advegax.schedule.commerce_reconcile")  # type: ignore[untyped-decorator]
def commerce_reconcile_task() -> int | None:
    rt = worker_runtime()
    ttl = int(rt.settings.SCHEDULE_COMMERCE_RECONCILE_TICK.total_seconds() * 0.9)
    return run_singleton(
        rt.redis,
        "commerce_reconcile",
        ttl,
        lambda: importer.enqueue_reconciliations(rt, importer.SyncMode.RECONCILE),
    )


@celery_app.task(name="advegax.schedule.commerce_deep")  # type: ignore[untyped-decorator]
def commerce_deep_task() -> int | None:
    rt = worker_runtime()
    ttl = int(rt.settings.SCHEDULE_COMMERCE_DEEP_INTERVAL.total_seconds() * 0.9)
    return run_singleton(
        rt.redis,
        "commerce_deep",
        ttl,
        lambda: importer.enqueue_reconciliations(rt, importer.SyncMode.DEEP),
    )
