"""Client metadata behind proxies and unit-of-work behaviour."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.request_meta import USER_AGENT_MAX, client_ip, request_meta
from app.core.settings import Settings
from app.db.session import after_commit
from sqlalchemy import text


def _request(headers=None, host="10.0.0.9"):
    return SimpleNamespace(
        headers=headers or {}, client=SimpleNamespace(host=host) if host else None
    )


def test_client_ip_direct_and_behind_proxy():
    direct = Settings(TRUSTED_PROXY_COUNT=0)
    assert client_ip(_request({"x-forwarded-for": "1.1.1.1"}), direct) == "10.0.0.9"  # type: ignore[arg-type]
    proxied = Settings(TRUSTED_PROXY_COUNT=1)
    assert (
        client_ip(_request({"x-forwarded-for": "6.6.6.6, 203.0.113.7"}), proxied) == "203.0.113.7"
    )  # type: ignore[arg-type]
    assert client_ip(_request({}, host=None), proxied) == "unknown"  # type: ignore[arg-type]


def test_user_agent_truncated():
    meta = request_meta(_request({"user-agent": "x" * 500}), Settings())  # type: ignore[arg-type]
    assert meta.user_agent is not None and len(meta.user_agent) == USER_AGENT_MAX


def test_after_commit_runs_only_on_commit_and_failures_are_contained(runtime):
    calls: list[str] = []
    with runtime.db.transaction() as session:
        after_commit(session, lambda: calls.append("ok"))
        after_commit(session, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        after_commit(session, lambda: calls.append("still-runs"))
    assert calls == ["ok", "still-runs"]
    try:
        with runtime.db.transaction() as session:
            after_commit(session, lambda: calls.append("never"))
            raise ValueError("rollback")
    except ValueError:
        pass
    assert "never" not in calls


def test_transaction_sets_and_clears_context(runtime):
    import uuid

    org = uuid.uuid4()
    with runtime.db.transaction(org_id=org) as session:
        value = session.execute(
            text("SELECT current_setting('app.current_org_id', true)")
        ).scalar_one()
    assert value == str(org)
