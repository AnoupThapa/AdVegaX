"""Single-use connect state (CSRF protection for platform authorization flows).

The state is a random token; its hash keys a short-lived Redis entry holding the user,
organization, provider and PKCE verifier. ``GETDEL`` makes it single-use. The callback takes
the organization **only** from this state, never from query parameters (D11).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

import redis

from app.core.errors import ServiceUnavailable
from app.core.security.tokens import generate_token, hash_token

_PREFIX = "connect-state:"


@dataclass(frozen=True)
class ConnectState:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    provider: str
    code_verifier: str | None
    # Validated connect parameters (e.g. Shopify shop domain), kept server-side only.
    provider_params: dict[str, str] = field(default_factory=dict)


def create_state(client: redis.Redis, state: ConnectState, ttl: timedelta) -> str:
    token = generate_token()
    payload = json.dumps(
        {
            "organization_id": str(state.organization_id),
            "user_id": str(state.user_id),
            "provider": state.provider,
            "code_verifier": state.code_verifier,
            "provider_params": state.provider_params,
        }
    )
    try:
        client.set(_PREFIX + hash_token(token), payload, ex=int(ttl.total_seconds()))
    except redis.RedisError:
        raise ServiceUnavailable() from None
    return token


def consume_state(client: redis.Redis, token: str | None) -> ConnectState | None:
    if not token or len(token) > 256:
        return None
    try:
        raw = client.getdel(_PREFIX + hash_token(token))
    except redis.RedisError:
        raise ServiceUnavailable() from None
    if raw is None:
        return None
    data = json.loads(raw)
    return ConnectState(
        organization_id=uuid.UUID(data["organization_id"]),
        user_id=uuid.UUID(data["user_id"]),
        provider=data["provider"],
        code_verifier=data["code_verifier"],
        provider_params=dict(data.get("provider_params") or {}),
    )
