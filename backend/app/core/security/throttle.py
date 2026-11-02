"""Fixed-window rate limiting backed by Redis (PHASE_01A_PLAN §9)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import redis

from app.core.clock import Clock
from app.core.errors import RateLimited, ServiceUnavailable
from app.core.security.tokens import hash_token

logger = logging.getLogger("advegax.throttle")


@dataclass(frozen=True)
class Limit:
    name: str
    max_requests: int
    window_seconds: int


class Throttler:
    def __init__(self, client: redis.Redis, clock: Clock, *, fail_open: bool) -> None:
        self._client = client
        self._clock = clock
        self._fail_open = fail_open

    def hit(self, limit: Limit, subject: str) -> None:
        """Count one request for ``subject``; raise RateLimited when over the limit."""
        window = int(self._clock.now().timestamp()) // limit.window_seconds
        key = f"throttle:{limit.name}:{hash_token(subject)[:32]}:{window}"
        try:
            pipe = self._client.pipeline()
            pipe.incr(key)
            pipe.expire(key, limit.window_seconds + 5)
            count = int(pipe.execute()[0])
        except redis.RedisError:
            logger.warning("throttle_backend_unavailable", extra={"limit": limit.name})
            if self._fail_open:
                return
            raise ServiceUnavailable() from None
        if count > limit.max_requests:
            logger.info("throttle_limited", extra={"limit": limit.name})
            raise RateLimited()
