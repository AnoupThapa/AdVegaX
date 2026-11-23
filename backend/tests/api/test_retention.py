"""Data retention (Phase 15, task 15-01): unlinked resources are deleted with their imported
data after the retention period; linked ones, recently unlinked ones and audit logs stay."""

from __future__ import annotations

from datetime import timedelta

from app.domains.retention import service as retention
from app.workers.celery_app import celery_app

from tests.api.test_actions_api import rows
from tests.helpers import connected


def _resources(c, org, conn):
    return c.get(f"/organizations/{org}/connections/{conn}/resources").json()["data"]


def test_unlinked_data_is_deleted_after_the_retention(runtime, make_client, clock, admin_engine):
    runtime.settings = runtime.settings.model_copy(update={"RETENTION_ENABLED": True})
    c = make_client()
    c.signup("retention@example.com")
    org = c.create_org("Keep Co")["id"]
    conn = connected(c, org)
    found = {r["external_id"]: r["id"] for r in _resources(c, org, conn)}
    gone, kept, relinked = found["fake-acct-101"], found["fake-acct-102"], found["fake-store-1"]
    for rid in (gone, kept, relinked):
        assert c.post(f"/organizations/{org}/resources/{rid}/link").status_code == 201
    for rid in (gone, relinked):
        assert c.post(f"/organizations/{org}/resources/{rid}/unlink").status_code == 200

    clock.advance(timedelta(days=89))
    assert retention.purge(runtime) == 0  # not yet
    assert c.login("retention@example.com").status_code == 200
    assert c.post(f"/organizations/{org}/resources/{relinked}/link").status_code == 201
    clock.advance(timedelta(days=2))
    assert retention.purge(runtime) == 1
    left = {r["id"] for r in rows(admin_engine, "SELECT id::text FROM external_resources")}
    assert gone not in left and {kept, relinked} <= left
    audit = rows(
        admin_engine,
        "SELECT resource_id, before_json AS before FROM audit_logs "
        "WHERE action = 'retention.resource_deleted'",
    )
    assert audit == [
        {"resource_id": gone, "before": {"kind": "ad_account", "external_id": "fake-acct-101"}}
    ]
    assert rows(admin_engine, "SELECT count(*) AS n FROM audit_logs")[0]["n"] > 1
    assert retention.purge(runtime) == 0


def test_off_by_default_and_scheduled(runtime):
    assert retention.purge(runtime) == 0
    assert celery_app.conf.beat_schedule["retention"]["task"] == "advegax.schedule.retention"
