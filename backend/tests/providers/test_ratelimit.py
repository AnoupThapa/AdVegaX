"""Token-bucket rate limiter for provider calls."""

from __future__ import annotations

from datetime import timedelta

import pytest
import redis
from app.providers.base.errors import RateLimitedError, RetryableError
from app.providers.http.ratelimit import ProviderRateLimiter


def test_bucket_allows_burst_then_limits_then_refills(runtime, clock):
    limiter = ProviderRateLimiter(runtime.redis, clock)
    for _ in range(3):
        limiter.acquire("fake:conn-1", rate_per_second=1.0, burst=3)
    with pytest.raises(RateLimitedError) as exc:
        limiter.acquire("fake:conn-1", rate_per_second=1.0, burst=3)
    assert 0 < exc.value.retry_after_seconds <= 1
    limiter.acquire("fake:conn-2", rate_per_second=1.0, burst=3)  # independent key
    clock.advance(timedelta(seconds=2))
    limiter.acquire("fake:conn-1", rate_per_second=1.0, burst=3)


def test_unavailable_backend_is_retryable(runtime, clock, monkeypatch):
    limiter = ProviderRateLimiter(runtime.redis, clock)

    def broken(*_a, **_k):
        raise redis.ConnectionError("down")

    monkeypatch.setattr(limiter, "_script", broken)
    with pytest.raises(RetryableError, match="rate_limiter_unavailable"):
        limiter.acquire("k", rate_per_second=1, burst=1)
