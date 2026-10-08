"""Background jobs: retry/backoff, dead-letter, failures, tenant re-check, recovery, scheduling."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from app.domains.jobs.service import JobOutcome, backoff_seconds, recover_stuck_jobs, run_job
from app.providers.fake import provider as fake
from app.workers import job_tasks
from sqlalchemy import text

from tests.helpers import connected


@pytest.fixture
def linked(make_client):
    c = make_client()
    c.signup("jobs@example.com")
    org = c.create_org("Jobs Co")["id"]
    conn = connected(c, org)
    rid = c.get(f"/organizations/{org}/connections/{conn}/resources").json()["data"][0]["id"]
    c.post(f"/organizations/{org}/resources/{rid}/link")
    return c, org, rid


def _job(admin_engine, job_id):
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT status, attempts, last_error_code, next_attempt_at > now() AS deferred, "
                "organization_id FROM job_runs WHERE id = :i"
            ),
            {"i": job_id},
        ).one()


def _make_due(admin_engine, job_id):
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE job_runs SET next_attempt_at = now() - interval '1 second' WHERE id = :i"),
            {"i": job_id},
        )


def test_rate_limited_job_is_retried_with_backoff_then_succeeds(linked, admin_engine, runtime):
    c, org, rid = linked
    fake.behaviour.rate_limited_times = 1
    job_id = c.post(f"/organizations/{org}/resources/{rid}/sync").json()["data"]["id"]
    status, attempts, code, deferred, _ = _job(admin_engine, job_id)
    assert (status, attempts, code, deferred) == ("queued", 1, "rate_limited", True)
    assert run_job(runtime, uuid.UUID(job_id), job_tasks.HANDLERS) is JobOutcome.SKIPPED  # not due
    _make_due(admin_engine, job_id)
    assert job_tasks.run_job_task(job_id) == "succeeded"
    assert _job(admin_engine, job_id)[:2] == ("succeeded", 2)


def test_retryable_failures_end_in_dead_letter(linked, admin_engine, runtime, settings):
    c, org, rid = linked
    fake.behaviour.retryable_failures = settings.JOB_MAX_ATTEMPTS
    job_id = c.post(f"/organizations/{org}/resources/{rid}/sync").json()["data"]["id"]
    for _ in range(settings.JOB_MAX_ATTEMPTS - 1):
        _make_due(admin_engine, job_id)
        run_job(runtime, uuid.UUID(job_id), job_tasks.HANDLERS)
    status, attempts, code, _, _ = _job(admin_engine, job_id)
    assert (status, attempts, code) == ("dead", settings.JOB_MAX_ATTEMPTS, "retryable")
    view = c.get(f"/organizations/{org}/jobs/{job_id}").json()["data"]
    assert view["status"] == "dead"
    assert set(view) == {"id", "job_type", "status", "attempts", "max_attempts", "last_error_code"}


def test_subject_gone_and_unknown_type_fail_without_retry(linked, admin_engine, runtime):
    c, org, rid = linked
    fake.behaviour.rate_limited_times = 1
    job_id = c.post(f"/organizations/{org}/resources/{rid}/sync").json()["data"]["id"]
    c.post(f"/organizations/{org}/resources/{rid}/unlink")  # subject no longer linked
    _make_due(admin_engine, job_id)
    assert run_job(runtime, uuid.UUID(job_id), job_tasks.HANDLERS) is JobOutcome.FAILED
    assert _job(admin_engine, job_id)[2] == "subject_not_found"

    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE job_runs SET status = 'queued', job_type = 'mystery.job', "
                "next_attempt_at = now() - interval '1 second' WHERE id = :i"
            ),
            {"i": job_id},
        )
    assert run_job(runtime, uuid.UUID(job_id), job_tasks.HANDLERS) is JobOutcome.FAILED
    assert _job(admin_engine, job_id)[2] == "unknown_job_type"


def test_unexpected_errors_are_retried_with_code_only(linked, admin_engine, runtime, monkeypatch):
    c, org, rid = linked

    def explode(*_a, **_k):
        raise RuntimeError("secret=abc should never be stored")

    monkeypatch.setattr(fake.FakeProvider, "sync_resource", explode)
    job_id = c.post(f"/organizations/{org}/resources/{rid}/sync").json()["data"]["id"]
    status, _, code, deferred, _ = _job(admin_engine, job_id)
    assert (status, code, deferred) == ("queued", "internal_error", True)


def test_job_cannot_cross_tenants(linked, admin_engine, runtime, make_client):
    c, org, rid = linked
    fake.behaviour.rate_limited_times = 1
    job_id = c.post(f"/organizations/{org}/resources/{rid}/sync").json()["data"]["id"]
    other = make_client()
    other.signup("other-tenant@example.com")
    other_org = other.create_org("Other")["id"]
    with admin_engine.begin() as conn:  # simulate a corrupted/forged job pointing at another tenant
        conn.execute(
            text(
                "UPDATE job_runs SET organization_id = :o, next_attempt_at = now() "
                "- interval '1 second' WHERE id = :i"
            ),
            {"o": other_org, "i": job_id},
        )
    assert run_job(runtime, uuid.UUID(job_id), job_tasks.HANDLERS) is JobOutcome.FAILED
    assert _job(admin_engine, job_id)[2] == "subject_not_found"


def test_stuck_job_recovery(linked, admin_engine, runtime, settings):
    c, org, rid = linked
    fake.behaviour.rate_limited_times = 1
    job_id = c.post(f"/organizations/{org}/resources/{rid}/sync").json()["data"]["id"]
    stuck = int(settings.JOB_STUCK_AFTER.total_seconds()) + 60
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE job_runs SET status = 'running', started_at = now() - "
                f"interval '{stuck} seconds' WHERE id = :i"
            ),
            {"i": job_id},
        )
    assert recover_stuck_jobs(runtime) == 1  # requeued and re-dispatched (eager → succeeds)
    assert _job(admin_engine, job_id)[0] == "succeeded"
    assert recover_stuck_jobs(runtime) == 0


def test_scheduler_singleton_lock(runtime):
    calls: list[int] = []
    assert job_tasks.run_singleton(runtime.redis, "t", 60, lambda: calls.append(1) or 7) == 7
    assert job_tasks.run_singleton(runtime.redis, "t", 60, lambda: calls.append(2) or 8) is None
    assert calls == [1]


def test_scheduled_tasks_run_once_per_window(runtime):
    assert job_tasks.email_sweep_task() == 0
    assert job_tasks.email_sweep_task() is None
    assert job_tasks.job_recovery_task() == 0
    assert job_tasks.job_recovery_task() is None


def test_email_sweep_delivers_pending_outbox(client, admin_engine, runtime):
    from app.domains.notifications.email import memory

    memory.FAIL_NEXT.append(True)
    client.register("sweep@example.com")
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE email_outbox SET next_attempt_at = now() - interval '1 second'"))
    assert job_tasks.email_sweep_task() == 1


def test_backoff_is_exponential_capped_and_respects_retry_after(settings):
    first = backoff_seconds(settings, 1, None)
    base = settings.JOB_RETRY_BASE_DELAY.total_seconds()
    assert 0.8 * base <= first <= 1.2 * base
    assert backoff_seconds(settings, 30, None) <= settings.JOB_RETRY_MAX_DELAY.total_seconds() * 1.2
    assert backoff_seconds(settings, 1, 3600) >= 3600
    assert settings.JOB_RETRY_BASE_DELAY <= settings.JOB_RETRY_MAX_DELAY < timedelta(days=1)
