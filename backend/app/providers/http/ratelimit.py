"""Redis token-bucket rate limiter for provider calls (per provider + connection/resource)."""

from __future__ import annotations

import redis

from app.core.clock import Clock
from app.providers.base.errors import RateLimitedError, RetryableError

_BUCKET_LUA = """
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local tokens = tonumber(data[1]) or burst
local ts = tonumber(data[2]) or now
if now > ts then tokens = math.min(burst, tokens + (now - ts) * rate) end
local allowed = 0
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  wait = (1 - tokens) / rate
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', math.max(now, ts))
redis.call('EXPIRE', KEYS[1], math.ceil(burst / rate) + 5)
return {allowed, tostring(wait)}
"""


class ProviderRateLimiter:
    def __init__(self, client: redis.Redis, clock: Clock) -> None:
        self._script = client.register_script(_BUCKET_LUA)
        self._clock = clock

    def acquire(self, key: str, *, rate_per_second: float, burst: int) -> None:
        """Take one token or raise ``RateLimitedError`` with the wait in seconds."""
        try:
            allowed, wait = self._script(
                keys=[f"provider-rate:{key}"],
                args=[rate_per_second, burst, self._clock.now().timestamp()],
            )
        except redis.RedisError:
            raise RetryableError("rate_limiter_unavailable") from None
        if int(allowed) != 1:
            raise RateLimitedError(retry_after_seconds=float(wait))
