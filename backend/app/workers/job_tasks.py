"""Celery entry points for durable jobs and scheduled maintenance (PHASE_01B_PLAN §11)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping

import redis

from app.domains.integrations import jobs as integration_jobs
from app.domains.integrations.service import JOB_DISCOVER, JOB_SYNC
from app.domains.jobs.service import Handler, JobOutcome, recover_stuck_jobs, run_job
from app.workers.celery_app import celery_app
from app.workers.email_tasks import deliver_pending, worker_runtime

HANDLERS: Mapping[str, Handler] = {
    JOB_DISCOVER: integration_jobs.discover,
    JOB_SYNC: integration_jobs.sync,
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
