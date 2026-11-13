"""The change engine's failure paths (QA audit QA-019): every way a send can go wrong ends in a
state a person can read, and nothing is sent twice or guessed at.

Reuses the Google Ads change fixtures of ``test_actions_api``.
"""

# ruff: noqa: F811 - the shared fixtures are imported, then requested by name
from __future__ import annotations

from app.domains.actions import engine
from sqlalchemy import text

from tests.api.test_actions_api import (  # noqa: F401 - pytest fixtures
    AU,
    ask,
    campaign,
    gsim,
    held,
    org,
    run,
)


def _approved(org, runtime, held):
    action = ask(org, org.search)
    assert org.post(f"{org.base}/{action['id']}/approve").status_code == 200
    return action, held.pop()


def _state(org, action):
    data = org.get(f"{org.base}/{action['id']}").json()["data"]
    return data["status"], data["error_code"]


def test_a_crash_while_sending_is_recorded_as_unknown_never_as_failed(
    org, gsim, held, runtime, monkeypatch
):
    """Anything unexpected during the send: we cannot know whether the change was made."""
    action, job = _approved(org, runtime, held)
    real = engine.platform_call
    calls = {"n": 0}

    def crash_on_send(rt, writer, org_id, connection_id, fn):
        calls["n"] += 1
        if calls["n"] == 2:  # the first call reads the campaign; the second sends the change
            raise RuntimeError("socket closed in an unexpected way")
        return real(rt, writer, org_id, connection_id, fn)

    monkeypatch.setattr(engine, "platform_call", crash_on_send)
    run(runtime, job)
    assert _state(org, action) == ("unknown", "outcome_unknown")
    assert held, "an unknown outcome is looked up later"


def test_a_platform_that_was_switched_off_fails_the_change_before_sending(
    org, gsim, held, runtime, monkeypatch
):
    action, job = _approved(org, runtime, held)
    monkeypatch.setattr(engine, "writer_for", lambda rt, provider: None)
    run(runtime, job)
    assert _state(org, action) == ("failed", "platform_unavailable")
    assert gsim.mutations == [] and campaign(gsim, "11")["status"] == "ENABLED"


def test_a_lasting_read_failure_fails_the_change_without_sending(
    org, gsim, held, runtime, admin_engine
):
    """The campaign cannot be read before sending: retried with back-off, then failed with
    "not sent" — never sent blind."""
    action, job = _approved(org, runtime, held)
    gsim.fail_next = [(500, {"internalError": "INTERNAL_ERROR"})] * 50
    for _ in range(20):
        run(runtime, job)
        with admin_engine.begin() as conn:  # past each back-off (the database's own clock)
            conn.execute(
                text("UPDATE job_runs SET next_attempt_at = now() WHERE id = :id"), {"id": job}
            )
        status, _ = _state(org, action)
        if status != "queued":
            break
    status, code = _state(org, action)
    assert status == "failed" and code
    events = org.get(f"{org.base}/{action['id']}").json()["data"]["events"]
    assert events[-1]["detail"].get("sent") is False
    assert gsim.mutations == []


def test_a_change_cancelled_after_approval_is_not_sent(org, gsim, held, runtime):
    action, job = _approved(org, runtime, held)
    cancelled = org.post(f"{org.base}/{action['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    run(runtime, job)  # the job finds a cancelled change and does nothing
    assert _state(org, action)[0] == "cancelled"
    assert gsim.mutations == []


def test_changes_paused_after_approval_wait_queued(org, gsim, held, runtime):
    action, job = _approved(org, runtime, held)
    saved = org.put(
        org.settings_url,
        {"paused": True, "require_second_person": False, "max_daily_budget": "500.00"},
    )
    assert saved.status_code == 200
    run(runtime, job)
    assert _state(org, action)[0] == "queued"
    assert gsim.mutations == []
    assert AU in gsim.customers


def test_the_sweep_looks_up_unknown_changes_a_bounded_number_of_times(
    org, gsim, held, runtime, admin_engine, clock
):
    """A change left "unknown" (its look-up message lost) is looked up again by the sweep,
    until the look-up limit; a queued change waits while changes are paused."""
    from datetime import timedelta

    unknown = ask(org, org.search)
    with admin_engine.begin() as db:
        db.execute(
            text("UPDATE actions SET status = 'unknown', updated_at = :t WHERE id = :i"),
            {"i": unknown["id"], "t": clock.now()},
        )
    assert engine.sweep(runtime) == 0  # not long enough ago
    clock.advance(runtime.settings.SCHEDULE_ACTIONS_SWEEP_INTERVAL + timedelta(seconds=1))
    assert engine.sweep(runtime) == 1
    held.clear()
    with admin_engine.begin() as db:
        db.execute(
            text("UPDATE actions SET reconcile_attempts = :n, updated_at = :t WHERE id = :i"),
            {
                "i": unknown["id"],
                "n": runtime.settings.ACTIONS_RECONCILE_ATTEMPTS,
                "t": clock.now(),
            },
        )
    clock.advance(runtime.settings.SCHEDULE_ACTIONS_SWEEP_INTERVAL + timedelta(seconds=1))
    assert engine.sweep(runtime) == 0  # the limit is reached: a person checks it
    assert held == []
