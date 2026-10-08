"""Background-job framework (PHASE_01B_PLAN §11).

``job_runs`` is the source of truth. A job is created inside the business transaction and
dispatched only after commit. The worker claims it with the system role (``FOR UPDATE SKIP
LOCKED``), runs the handler under the job's tenant context, and records the outcome:
retry with exponential backoff and jitter, dead-letter after ``max_attempts``, or failure
for non-retryable errors. Errors are stored as codes only — never payloads or secrets.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core.correlation import get_correlation_id, set_correlation_id
from app.core.errors import NotFound
from app.core.settings import Settings
from app.db.session import after_commit
from app.domains.jobs.models import JobRun
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.tenancy import TenantContext
from app.providers.base.errors import ProviderError, RateLimitedError
from app.runtime import Runtime

logger = logging.getLogger("advegax.jobs")


class JobSubjectGoneError(Exception):
    """The job's subject no longer exists in its tenant (or never did)."""


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    organization_id: uuid.UUID | None
    job_type: str
    subject_id: str | None
    attempts: int
    max_attempts: int
    requested_by_user_id: uuid.UUID | None
    correlation_id: str | None


Handler = Callable[[Runtime, ClaimedJob], None]


class JobOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    RETRY = "retry"
    FAILED = "failed"
    DEAD = "dead"
    SKIPPED = "skipped"


def create_job(
    session: Session,
    rt: Runtime,
    *,
    organization_id: uuid.UUID,
    job_type: str,
    subject_type: str,
    subject_id: uuid.UUID,
    requested_by: uuid.UUID | None,
) -> JobRun:
    job = JobRun(
        organization_id=organization_id,
        job_type=job_type,
        subject_type=subject_type,
        subject_id=str(subject_id),
        max_attempts=rt.settings.JOB_MAX_ATTEMPTS,
        correlation_id=get_correlation_id(),
        requested_by_user_id=requested_by,
    )
    session.add(job)
    session.flush()
    job_id = job.id
    after_commit(session, lambda: rt.enqueue_job(job_id, 0))
    return job


def backoff_seconds(settings: Settings, attempts: int, retry_after: float | None) -> int:
    base = settings.JOB_RETRY_BASE_DELAY.total_seconds() * (2 ** max(0, attempts - 1))
    capped = min(base, settings.JOB_RETRY_MAX_DELAY.total_seconds())
    jittered = capped * random.uniform(0.8, 1.2)  # noqa: S311 - jitter, not security
    return max(1, int(max(jittered, retry_after or 0)))


def _claim(rt: Runtime, job_id: uuid.UUID) -> ClaimedJob | None:
    with rt.db.transaction(system=True) as session:
        job = session.execute(
            select(JobRun)
            .where(
                JobRun.id == job_id, JobRun.status == "queued", JobRun.next_attempt_at <= func.now()
            )
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if job is None:
            return None
        job.status = "running"
        job.attempts += 1
        job.started_at = func.now()
        job.updated_at = func.now()
        session.flush()
        return ClaimedJob(
            job.id,
            job.organization_id,
            job.job_type,
            job.subject_id,
            job.attempts,
            job.max_attempts,
            job.requested_by_user_id,
            job.correlation_id,
        )


def _finish(
    rt: Runtime, job_id: uuid.UUID, status: str, code: str | None, delay_seconds: int | None = None
) -> None:
    values: dict[str, object] = {
        "status": status,
        "last_error_code": code,
        "updated_at": func.now(),
    }
    if delay_seconds is None:
        values["finished_at"] = func.now()
    else:
        values["next_attempt_at"] = func.now() + text(f"interval '{int(delay_seconds)} seconds'")
    with rt.db.transaction(system=True) as session:
        session.execute(update(JobRun).where(JobRun.id == job_id).values(**values))


def run_job(rt: Runtime, job_id: uuid.UUID, handlers: Mapping[str, Handler]) -> JobOutcome:
    claimed = _claim(rt, job_id)
    if claimed is None:
        return JobOutcome.SKIPPED
    previous = get_correlation_id()
    set_correlation_id(claimed.correlation_id)
    try:
        handler = handlers.get(claimed.job_type)
        if handler is None or claimed.organization_id is None:
            _finish(rt, claimed.id, "failed", "unknown_job_type")
            return JobOutcome.FAILED
        try:
            handler(rt, claimed)
        except JobSubjectGoneError:
            _finish(rt, claimed.id, "failed", "subject_not_found")
            return JobOutcome.FAILED
        except ProviderError as exc:
            if not exc.retryable:
                _finish(rt, claimed.id, "failed", exc.code)
                return JobOutcome.FAILED
            retry_after = exc.retry_after_seconds if isinstance(exc, RateLimitedError) else None
            return _retry(rt, claimed, exc.code, retry_after)
        except Exception:
            logger.exception(
                "job_handler_error", extra={"job_id": str(claimed.id), "job_type": claimed.job_type}
            )
            return _retry(rt, claimed, "internal_error", None)
        _finish(rt, claimed.id, "succeeded", None)
        return JobOutcome.SUCCEEDED
    finally:
        set_correlation_id(previous)


def _retry(rt: Runtime, job: ClaimedJob, code: str, retry_after: float | None) -> JobOutcome:
    if job.attempts >= job.max_attempts:
        _finish(rt, job.id, "dead", code)
        logger.error("job_dead_lettered", extra={"job_id": str(job.id), "error_code": code})
        return JobOutcome.DEAD
    delay = backoff_seconds(rt.settings, job.attempts, retry_after)
    _finish(rt, job.id, "queued", code, delay_seconds=delay)
    rt.enqueue_job(job.id, delay)
    return JobOutcome.RETRY


def recover_stuck_jobs(rt: Runtime) -> int:
    """Requeue abandoned running jobs and re-dispatch queued jobs whose message was lost."""
    stuck = int(rt.settings.JOB_STUCK_AFTER.total_seconds())
    cutoff = func.now() - text(f"interval '{stuck} seconds'")
    with rt.db.transaction(system=True) as session:
        abandoned = list(
            session.execute(
                update(JobRun)
                .where(JobRun.status == "running", JobRun.started_at <= cutoff)
                .values(
                    status="queued",
                    last_error_code="abandoned",
                    next_attempt_at=func.now(),
                    updated_at=func.now(),
                )
                .returning(JobRun.id)
            ).scalars()
        )
        lost = list(
            session.execute(
                select(JobRun.id)
                .where(JobRun.status == "queued", JobRun.next_attempt_at <= cutoff)
                .limit(500)
            ).scalars()
        )
    ids = list(dict.fromkeys([*abandoned, *lost]))
    for job_id in ids:
        rt.enqueue_job(job_id, 0)
    if ids:
        logger.warning("jobs_recovered", extra={"count": len(ids)})
    return len(ids)


@dataclass(frozen=True)
class JobView:
    id: uuid.UUID
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    last_error_code: str | None


def get_job(rt: Runtime, ctx: TenantContext, job_id: uuid.UUID) -> JobView:
    authorize(ctx, Permission.JOBS_VIEW)
    with rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
        job = session.execute(
            select(JobRun).where(JobRun.id == job_id, JobRun.organization_id == ctx.organization_id)
        ).scalar_one_or_none()
        if job is None:
            raise NotFound()
        return JobView(
            job.id, job.job_type, job.status, job.attempts, job.max_attempts, job.last_error_code
        )
