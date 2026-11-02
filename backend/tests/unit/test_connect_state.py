"""Connect state: single use, bounded input, fail-closed on Redis errors."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import redis
from app.core.errors import ServiceUnavailable
from app.domains.integrations.connect_state import ConnectState, consume_state, create_state
from app.domains.integrations.credentials import load_secrets
from app.providers.base.errors import AuthExpiredError


def test_single_use_round_trip(runtime):
    state = ConnectState(uuid.uuid4(), uuid.uuid4(), "fake", "verifier")
    token = create_state(runtime.redis, state, timedelta(minutes=10))
    assert consume_state(runtime.redis, token) == state
    assert consume_state(runtime.redis, token) is None
    assert consume_state(runtime.redis, None) is None
    assert consume_state(runtime.redis, "x" * 300) is None


def test_redis_failures_fail_closed(runtime, monkeypatch):
    def broken(*_a, **_k):
        raise redis.ConnectionError("down")

    monkeypatch.setattr(runtime.redis, "set", broken)
    monkeypatch.setattr(runtime.redis, "getdel", broken)
    with pytest.raises(ServiceUnavailable):
        create_state(
            runtime.redis,
            ConnectState(uuid.uuid4(), uuid.uuid4(), "fake", None),
            timedelta(minutes=1),
        )
    with pytest.raises(ServiceUnavailable):
        consume_state(runtime.redis, "a" * 43)


def test_missing_credentials_are_treated_as_expired(runtime):
    from types import SimpleNamespace

    class NoRows:
        def get(self, *_a):
            return None

    connection = SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4(), provider="fake")
    with pytest.raises(AuthExpiredError, match="credentials_missing"):
        load_secrets(NoRows(), runtime.cipher, connection)  # type: ignore[arg-type]
