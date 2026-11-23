"""The campaign builder's failure paths (QA audit QA-019): a launch that cannot run ends in a
state a person can read, nothing is created blind, and nothing is created twice.

Reuses the builder fixtures of ``test_builder_api``.
"""

# ruff: noqa: F811 - the shared fixtures are imported, then requested by name
from __future__ import annotations

from app.domains.builder import launch
from sqlalchemy import text

from tests.api.test_actions_api import gsim, held, run  # noqa: F401  (fixtures)
from tests.api.test_actions_meta import msim  # noqa: F401  (fixture)
from tests.api.test_builder_api import AU, _launch, _ready, builder  # noqa: F401
from tests.api.test_creatives_api import maker  # noqa: F401  (fixture)
from tests.api.test_strategies_api import owner  # noqa: F401  (fixture)
from tests.api.test_strategy_context import shop  # noqa: F401  (fixture)


def _approved_launch(b, held):
    draft = _ready(b)
    action = _launch(b, draft)
    assert b.post(f"{b.actions}/{action['id']}/approve").status_code == 200
    return draft, action, held.pop()


def _state(b, action):
    data = b.get(f"{b.actions}/{action['id']}").json()["data"]
    return data["status"], data["error_code"]


def _created(b, draft):
    return [
        r
        for r in b.gsim.customers[AU].campaigns
        if draft["reference"] in r["campaign"].get("name", "")
    ]


def test_a_crash_while_creating_is_unknown_and_looked_up(builder, held, runtime, monkeypatch):
    _, action, job = _approved_launch(builder, held)
    real = launch.engine.platform_call
    calls = {"n": 0}

    def crash_on_create(rt, writer, org_id, connection_id, fn):
        calls["n"] += 1
        if calls["n"] == 2:  # after the "already made?" look-up: the create call itself
            raise RuntimeError("connection dropped in an unexpected way")
        return real(rt, writer, org_id, connection_id, fn)

    monkeypatch.setattr(launch.engine, "platform_call", crash_on_create)
    run(runtime, job)
    status, code = _state(builder, action)
    assert (status, code) == ("unknown", "outcome_unknown")
    assert held, "an unknown outcome is looked up later, never sent again blind"


def test_a_platform_switched_off_after_approval_fails_before_sending(
    builder, held, runtime, monkeypatch
):
    draft, action, job = _approved_launch(builder, held)
    monkeypatch.setattr(launch, "builder_for", lambda rt, provider: None)
    run(runtime, job)
    assert _state(builder, action) == ("failed", "platform_unavailable")
    assert _created(builder, draft) == []


def test_a_lasting_failure_to_look_first_creates_nothing(builder, held, runtime, admin_engine):
    """The "does it already exist?" look-up keeps failing: retried, then failed as not sent."""
    draft, action, job = _approved_launch(builder, held)
    builder.gsim.fail_next = [(500, {"internalError": "INTERNAL_ERROR"})] * 60
    for _ in range(20):
        run(runtime, job)
        with admin_engine.begin() as conn:  # past each back-off (the database's own clock)
            conn.execute(
                text("UPDATE job_runs SET next_attempt_at = now() WHERE id = :id"), {"id": job}
            )
        if _state(builder, action)[0] != "queued":
            break
    status, code = _state(builder, action)
    assert status == "failed" and code
    events = builder.get(f"{builder.actions}/{action['id']}").json()["data"]["events"]
    assert events[-1]["detail"].get("sent") is False
    assert _created(builder, draft) == []


def test_a_draft_changed_while_queued_goes_stale(builder, held, runtime, monkeypatch):
    draft, action, job = _approved_launch(builder, held)
    monkeypatch.setattr(launch, "preconditions", lambda c, kind: "draft_not_launchable")
    run(runtime, job)
    assert _state(builder, action) == ("stale", "draft_not_launchable")
    assert _created(builder, draft) == []


def test_a_cancelled_launch_is_not_sent(builder, held, runtime):
    draft, action, job = _approved_launch(builder, held)
    assert builder.post(f"{builder.actions}/{action['id']}/cancel").status_code == 200
    run(runtime, job)
    assert _state(builder, action)[0] == "cancelled"
    assert _created(builder, draft) == []
