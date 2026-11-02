"""Credential lifecycle (task 2A-04, PHASE_02A_PLAN §6.6-§6.8).

Refresh before expiry, rotation saved, keep-alive sweep, refresh failures → "Needs
reconnecting", no concurrent refreshes or refresh-vs-reconnect overlap (account lock), and
platform-side revocation (uninstall). Uses the fake platform and the Shopify simulator.
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.integrations import jobs as integration_jobs
from app.domains.integrations import tokens
from app.domains.integrations.service import IntegrationService
from app.domains.integrations.tokens import AccountBusy, account_lock, lock_key, usable_secrets
from app.providers.base.errors import AuthExpiredError, RetryableError
from app.providers.fake import provider as fake
from sqlalchemy import text

from tests.helpers import connected
from tests.shopify_sim import ShopifySim, build_provider, callback_params

SHOP = "eve-zone.myshopify.com"


@pytest.fixture
def owner(make_client):
    c = make_client()
    c.signup("tokens-owner@example.com")
    c.org = c.create_org("Token Co")["id"]
    return c


def _credential(admin_engine, connection_id):
    with admin_engine.begin() as db:
        return db.execute(
            text(
                "SELECT ciphertext, token_expires_at, refresh_expires_at, last_refreshed_at "
                "FROM external_connection_credentials WHERE connection_id = :id"
            ),
            {"id": connection_id},
        ).one()


def _status(owner, conn):
    return owner.get(f"/organizations/{owner.org}/connections/{conn}").json()["data"]


# ------------------------------------------------------------------ refresh before use
def test_refreshes_before_use_when_the_access_token_is_about_to_expire(
    owner, runtime, clock, admin_engine
):
    conn = connected(owner, owner.org)
    before = _credential(admin_engine, conn)
    fake.behaviour.calls.clear()
    clock.advance(timedelta(minutes=55))  # 5 minutes left < 10-minute margin
    secrets = usable_secrets(runtime, uuid.UUID(owner.org), uuid.UUID(conn))
    assert fake.behaviour.calls == ["refresh"]
    after = _credential(admin_engine, conn)
    assert after.ciphertext != before.ciphertext  # rotated pair saved, encrypted
    assert after.token_expires_at > before.token_expires_at
    assert after.last_refreshed_at is not None
    assert secrets["refresh_token"].startswith("fake-rt-")


def test_no_refresh_while_the_access_token_is_fresh(owner, runtime):
    conn = connected(owner, owner.org)
    fake.behaviour.calls.clear()
    usable_secrets(runtime, uuid.UUID(owner.org), uuid.UUID(conn))
    assert "refresh" not in fake.behaviour.calls


def test_jobs_refresh_first_then_call_the_platform(owner, clock):
    conn = connected(owner, owner.org)
    fake.behaviour.calls.clear()
    clock.advance(timedelta(minutes=58))
    response = owner.post(f"/organizations/{owner.org}/connections/{conn}/rediscover")
    assert response.status_code == 202
    assert fake.behaviour.calls[:2] == ["refresh", "discover"]


def test_rejected_refresh_marks_the_connection_needs_reconnecting(
    owner, runtime, clock, admin_engine
):
    conn = connected(owner, owner.org)
    fake.behaviour.refresh_fails = True
    clock.advance(timedelta(minutes=58))
    with pytest.raises(AuthExpiredError):
        usable_secrets(runtime, uuid.UUID(owner.org), uuid.UUID(conn))
    detail = _status(owner, conn)
    assert (detail["status"], detail["last_error_code"]) == ("expired", "auth_expired")
    with admin_engine.begin() as db:
        actions = [
            r[0]
            for r in db.execute(
                text("SELECT action FROM audit_logs WHERE resource_id = :id ORDER BY created_at"),
                {"id": conn},
            )
        ]
    assert "connection.health_changed" in actions


# ------------------------------------------------------------------ concurrency
def test_concurrent_refreshes_reach_the_platform_once(owner, runtime, clock):
    """Two workers needing a refresh at the same time: the lock serializes them and the second
    sees the first one's fresh token instead of refreshing again (which would retire it)."""
    conn = connected(owner, owner.org)
    fake.behaviour.calls.clear()
    clock.advance(timedelta(minutes=58))
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            usable_secrets(runtime, uuid.UUID(owner.org), uuid.UUID(conn))
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert fake.behaviour.calls.count("refresh") == 1


def test_account_lock_is_exclusive_and_owner_released(runtime):
    key = f"token-lock:test:{uuid.uuid4()}"
    with account_lock(runtime.redis, key, wait_seconds=0.2):
        with pytest.raises(AccountBusy), account_lock(runtime.redis, key, wait_seconds=0.2):
            pass  # pragma: no cover
        assert isinstance(AccountBusy(), RetryableError)  # a job retries later
    with account_lock(runtime.redis, key, wait_seconds=0.2):  # released → available again
        pass
    runtime.redis.set(key, "someone-else", ex=60)
    with pytest.raises(AccountBusy), account_lock(runtime.redis, key, wait_seconds=0.1):
        pass  # pragma: no cover
    assert runtime.redis.get(key) == b"someone-else"  # never released by a non-owner
    runtime.redis.delete(key)


def test_reconnect_waits_for_a_refresh_and_reports_busy(make_client, runtime, clock, monkeypatch):
    sim = ShopifySim()
    sim.add_shop(SHOP)
    runtime.providers.register(build_provider(sim, clock))
    owner = make_client()
    owner.signup("busy@example.com")
    org = owner.create_org("Busy Co")["id"]
    started = owner.post(
        f"/organizations/{org}/connections/shopify/start", {"params": {"shop_domain": SHOP}}
    ).json()["data"]["authorize_url"]
    monkeypatch.setattr(tokens, "LOCK_WAIT_SECONDS", 0.2)
    key = lock_key("shopify", SHOP, uuid.uuid4())
    runtime.redis.set(key, "refresh-in-progress", ex=60)
    try:
        response = owner.http.get(
            "/api/v1/connections/shopify/callback",
            params=callback_params(started),
            follow_redirects=False,
        )
    finally:
        runtime.redis.delete(key)
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["code"] == ["account_busy"]
    assert sim.token_calls == []  # the exchange never ran while a refresh held the account


# ------------------------------------------------------------------ keep-alive sweep
def test_keepalive_sweep_refreshes_idle_connections_once(owner, runtime, clock, admin_engine):
    conn = connected(owner, owner.org)
    fake.behaviour.calls.clear()
    assert integration_jobs.enqueue_keepalive_refreshes(runtime) == 1  # never refreshed yet
    assert fake.behaviour.calls == ["refresh"]
    assert integration_jobs.enqueue_keepalive_refreshes(runtime) == 0  # just refreshed
    clock.advance(timedelta(hours=25))
    assert integration_jobs.enqueue_keepalive_refreshes(runtime) == 1
    assert fake.behaviour.calls == ["refresh", "refresh"]
    with admin_engine.begin() as db:
        status = db.execute(
            text("SELECT status FROM external_connections WHERE id = :id"), {"id": conn}
        ).scalar_one()
    assert status == "active"


def test_keepalive_sweep_skips_revoked_connections_and_pending_jobs(owner, runtime):
    first = connected(owner, owner.org)
    owner.post(f"/organizations/{owner.org}/connections/{first}/disconnect")
    connected(owner, owner.org)
    runtime.enqueue_job = lambda job_id, countdown=0: None  # leave jobs queued
    assert integration_jobs.enqueue_keepalive_refreshes(runtime) == 1  # revoked one skipped
    assert integration_jobs.enqueue_keepalive_refreshes(runtime) == 0  # already queued


def test_keepalive_task_is_scheduled_and_runs_once_per_window(runtime):
    from app.workers.celery_app import celery_app
    from app.workers.job_tasks import run_singleton

    schedule = celery_app.conf.beat_schedule["token-refresh"]
    assert schedule["task"] == "advegax.schedule.token_refresh"
    assert schedule["schedule"] == runtime.settings.SCHEDULE_TOKEN_REFRESH_INTERVAL.total_seconds()
    runtime.redis.delete("schedule-lock:token_refresh_test")
    assert run_singleton(runtime.redis, "token_refresh_test", 60, lambda: 7) == 7
    assert run_singleton(runtime.redis, "token_refresh_test", 60, lambda: 7) is None


# ------------------------------------------------------------------ Shopify refresh
@pytest.fixture
def shopify(runtime, clock):
    sim = ShopifySim()
    sim.add_shop(SHOP)
    runtime.providers.register(build_provider(sim, clock))
    return sim


def _connect_shopify(client, org):
    started = client.post(
        f"/organizations/{org}/connections/shopify/start", {"params": {"shop_domain": SHOP}}
    ).json()["data"]["authorize_url"]
    response = client.http.get(
        "/api/v1/connections/shopify/callback",
        params=callback_params(started),
        follow_redirects=False,
    )
    return parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]


def test_shopify_refresh_rotates_both_tokens(owner, runtime, clock, shopify):
    conn = _connect_shopify(owner, owner.org)
    clock.advance(timedelta(minutes=55))
    secrets = usable_secrets(runtime, uuid.UUID(owner.org), uuid.UUID(conn))
    (_, refresh) = shopify.token_calls
    form = parse_qs(refresh.content.decode())
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["shprt_sim_refresh_1"]
    assert secrets["refresh_token"] == "shprt_sim_refresh_2"  # the NEW refresh token is kept
    assert secrets["access_token"] == "shpat_sim_access_2"
    # The old refresh token is now retired: using it again would be refused by Shopify.
    shopify.token_status = 200
    clock.advance(timedelta(minutes=55))
    usable_secrets(runtime, uuid.UUID(owner.org), uuid.UUID(conn))
    third = parse_qs(shopify.token_calls[2].content.decode())
    assert third["refresh_token"] == ["shprt_sim_refresh_2"]


@pytest.mark.parametrize(("status", "error"), [(400, AuthExpiredError), (503, RetryableError)])
def test_shopify_refresh_failures(owner, runtime, clock, shopify, status, error):
    conn = _connect_shopify(owner, owner.org)
    clock.advance(timedelta(minutes=55))
    shopify.token_status = status
    with pytest.raises(error):
        usable_secrets(runtime, uuid.UUID(owner.org), uuid.UUID(conn))
    expected = "expired" if error is AuthExpiredError else "active"
    assert _status(owner, conn)["status"] == expected  # a temporary failure is just retried


# ------------------------------------------------------------------ platform revocation
def test_uninstall_revokes_tokens_and_links_but_keeps_data(owner, runtime, shopify, admin_engine):
    conn = _connect_shopify(owner, owner.org)
    (resource,) = owner.get(f"/organizations/{owner.org}/connections/{conn}/resources").json()[
        "data"
    ]
    owner.post(f"/organizations/{owner.org}/resources/{resource['id']}/link")
    service = IntegrationService(runtime, None)  # type: ignore[arg-type] - unused here
    assert service.revoke_by_platform("shopify", SHOP, reason="app_uninstalled") == 1
    detail = _status(owner, conn)
    assert detail["status"] == "revoked"
    assert detail["last_error_code"] == "app_uninstalled"
    resources = owner.get(f"/organizations/{owner.org}/connections/{conn}/resources").json()["data"]
    assert [r["id"] for r in resources] == [resource["id"]]  # data kept (D-2A-2)
    assert resources[0]["linked"] is False
    assert _credential(admin_engine, conn).ciphertext is None  # tokens deleted
    with admin_engine.begin() as db:
        action = db.execute(
            text(
                "SELECT actor_type, action FROM audit_logs WHERE resource_id = :id "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"id": conn},
        ).one()
    assert tuple(action) == ("system", "connection.revoked_by_platform")
    assert service.revoke_by_platform("shopify", SHOP, reason="app_uninstalled") == 0
    assert service.revoke_by_platform("shopify", "unknown.myshopify.com", reason="x") == 0
