"""Authentication throttling (§9 defaults, centralized settings)."""

from __future__ import annotations

import redis

from tests.helpers import PASSWORD


def test_login_throttled_per_account_and_ip(client, settings):
    client.register("t@example.com")
    for _ in range(settings.THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE):
        assert client.login("t@example.com", "wrong password here").status_code == 401
    limited = client.login("t@example.com")  # even the right password is refused now
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert client.login("other@example.com").status_code == 401  # different account still allowed


def test_window_resets_with_clock(client, clock, settings):
    from datetime import timedelta

    client.register("w@example.com")
    for _ in range(settings.THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE + 1):
        client.login("w@example.com", "wrong password here")
    clock.advance(timedelta(minutes=2))
    assert client.login("w@example.com").status_code == 200


def test_register_and_email_actions_throttled(client, settings):
    for i in range(settings.THROTTLE_REGISTER_PER_IP_PER_HOUR):
        assert client.register(f"r{i}@example.com").status_code == 202
    assert client.register("one-more@example.com").status_code == 429
    for _ in range(settings.THROTTLE_EMAIL_ACTION_PER_EMAIL_PER_HOUR):
        assert client.post("/auth/forgot-password", {"email": "r0@example.com"}).status_code == 202
    assert client.post("/auth/forgot-password", {"email": "r0@example.com"}).status_code == 429


def test_throttle_fails_closed_when_redis_unavailable(client, runtime, monkeypatch):
    def broken(*_a, **_k):
        raise redis.ConnectionError("down")

    monkeypatch.setattr(runtime.redis, "pipeline", broken)
    response = client.login("x@example.com", PASSWORD)
    assert response.status_code == 503


def test_throttle_can_fail_open_when_configured(runtime, monkeypatch):
    from app.core.security.throttle import Limit, Throttler

    def broken(*_a, **_k):
        raise redis.ConnectionError("down")

    monkeypatch.setattr(runtime.redis, "pipeline", broken)
    Throttler(runtime.redis, runtime.clock, fail_open=True).hit(Limit("x", 1, 60), "subject")
