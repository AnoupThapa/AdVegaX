"""The platform allowance shared by every AdVegaX customer (Phase 3, task 3-07, PLAN §9).

One Google Ads developer token serves the whole product, so its daily operations are counted
in one Redis counter per platform over a **sliding window** (24 hours by default). A step
reserves its operations before calling the platform: the reservation succeeds only if it fits
under the step's ceiling — the full allowance for first imports, 3-hour runs and "Sync now",
a share of it (80 %) for nightly and weekly re-reads, so those wait first. When the platform
itself says the allowance is used up, every account waits for the given delay (``block``).

The key names only the platform; no token or secret is ever part of it.
"""

from __future__ import annotations

import uuid

import redis

from app.core.clock import Clock
from app.providers.base.errors import RetryableError

# Atomically: drop entries older than the window, then add ``count`` entries if they fit.
_RESERVE_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local count = tonumber(ARGV[3])
local ceiling = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local used = redis.call('ZCARD', key)
if used + count > ceiling then
  return 0
end
for i = 1, count do
  redis.call('ZADD', key, now, ARGV[5] .. ':' .. i)
end
redis.call('EXPIRE', key, math.ceil(window) + 60)
return 1
"""


class SharedQuota:
    def __init__(self, client: redis.Redis, clock: Clock) -> None:
        self._redis = client
        self._clock = clock
        self._reserve = client.register_script(_RESERVE_LUA)

    @staticmethod
    def _key(platform: str) -> str:
        return f"ads-quota:{platform}"

    def reserve(self, platform: str, count: int, *, ceiling: int, window_seconds: float) -> bool:
        """Count ``count`` operations if the total stays at or under ``ceiling``."""
        if count <= 0:
            return True
        try:
            allowed = self._reserve(
                keys=[self._key(platform)],
                args=[
                    self._clock.now().timestamp(),
                    window_seconds,
                    count,
                    ceiling,
                    uuid.uuid4().hex,
                ],
            )
        except redis.RedisError:
            raise RetryableError("quota_counter_unavailable") from None
        return int(allowed) == 1

    def used(self, platform: str, *, window_seconds: float) -> int:
        now = self._clock.now().timestamp()
        try:
            return int(self._redis.zcount(self._key(platform), now - window_seconds, "+inf"))
        except redis.RedisError:
            raise RetryableError("quota_counter_unavailable") from None

    def block(self, platform: str, seconds: float) -> None:
        """The platform said its allowance is used up: every account waits ``seconds``."""
        until = self._clock.now().timestamp() + max(1.0, seconds)
        try:
            self._redis.set(f"ads-quota-blocked:{platform}", str(until), ex=int(seconds) + 1)
        except redis.RedisError:
            raise RetryableError("quota_counter_unavailable") from None

    def blocked_for(self, platform: str) -> float:
        """Seconds still to wait after the platform refused (0 when not blocked)."""
        try:
            value = self._redis.get(f"ads-quota-blocked:{platform}")
        except redis.RedisError:
            raise RetryableError("quota_counter_unavailable") from None
        if value is None:
            return 0.0
        try:
            remaining = float(value) - self._clock.now().timestamp()
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, remaining)
