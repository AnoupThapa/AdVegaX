"""The Action Engine against the Google Ads simulator (Phase 10A, tasks 10A-04 … 10A-07).

A linked Google Ads test account (AUD, Sydney) with the sample structure: the Search campaign
11 (active, daily budget AUD 50.00 — made unshared here) and the Performance Max campaign 12
(paused, a lifetime budget). The ECB rates of the test day make 1 USD = 1.60 AUD, so the
platform minimum is AUD 1.60. The organization's maximum is AUD 500.00.

Covers PLAN §9 and acceptance criteria 1, 3-7: checks and limits, the dry run, approval, the
second-person rule, both switches, read-before-write (stale), never a blind retry (unknown →
looked up), duplicates and two workers, verification, undo, cancel, reject, the sweep, roles
and tenants. No call leaves the machine.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from app.domains.actions import engine
from app.domains.integrations.tokens import account_lock
from app.domains.jobs.service import JobOutcome, run_job
from app.workers.job_tasks import HANDLERS
from sqlalchemy import text

from tests.google_ads_sim import GoogleAdsSim, build_provider, sample_hierarchy, sample_structure

SUB = "108000000000000000001"
AU = "1000000001"
DAY = "2026-10-14"  # the test clock's day


def rates(admin_engine, day=DAY):
    with admin_engine.begin() as db:
        for quote, rate in (("AUD", "1.6"), ("USD", "1.0")):
            db.execute(
                text(
                    "INSERT INTO fx_rates (source, base, quote, rate_date, rate, fetched_at) "
                    "VALUES ('ecb', 'EUR', :q, :d, :r, now())"
                ),
                {"q": quote, "d": day, "r": Decimal(rate)},
            )


def rows(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def campaign_id(admin_engine, external):
    (row,) = rows(
        admin_engine,
        "SELECT id FROM ad_campaigns WHERE external_campaign_id = :e",
        e=external,
    )
    return str(row["id"])


@pytest.fixture
def gsim(runtime, clock):
    s = sample_hierarchy(GoogleAdsSim(clock=clock))
    sample_structure(s.customers[AU])
    s.customers[AU].budgets[0]["campaignBudget"]["explicitlyShared"] = False
    runtime.providers.register(build_provider(s))
    return s


def enable(runtime, **more):
    runtime.settings = runtime.settings.model_copy(update={"ACTIONS_ENABLED": True, **more})


@pytest.fixture
def org(make_client, gsim, runtime, admin_engine):
    """An owner whose Google Ads account is linked and imported, changes allowed."""
    rates(admin_engine)
    enable(runtime)
    c = make_client()
    c.signup(f"actions-{uuid.uuid4().hex[:6]}@example.com")
    c.org = c.create_org("Eve Zone")["id"]
    started = c.post(f"/organizations/{c.org}/connections/google_ads/start", {"params": {}})
    response = c.http.get(
        "/api/v1/connections/google_ads/callback",
        params=gsim.approve(started.json()["data"]["authorize_url"], SUB),
        follow_redirects=False,
    )
    c.conn = parse_qs(urlsplit(response.headers["location"]).query)["connection_id"][0]
    resources = c.get(f"/organizations/{c.org}/connections/{c.conn}/resources").json()["data"]
    found = {r["external_id"]: r for r in resources}
    assert c.post(f"/organizations/{c.org}/resources/{found[AU]['id']}/link").status_code == 201
    c.base = f"/organizations/{c.org}/actions"
    c.settings_url = f"/organizations/{c.org}/action-settings"
    c.access = f"/organizations/{c.org}/connections/{c.conn}/write-access"
    assert c.put(c.access, {"allowed": True}).status_code == 200
    saved = c.put(
        c.settings_url,
        {"paused": False, "require_second_person": False, "max_daily_budget": "500.00"},
    )
    assert saved.status_code == 200, saved.text
    c.search = campaign_id(admin_engine, "11")
    c.pmax = campaign_id(admin_engine, "12")
    return c


def body(campaign, action_type="campaign.pause", **params):
    return {"action_type": action_type, "campaign_id": campaign, "params": params}


def ask(c, campaign, action_type="campaign.pause", **params):
    response = c.post(c.base, body(campaign, action_type, **params))
    assert response.status_code == 201, response.text
    return response.json()["data"]


def reasons(response):
    return [d.get("reason") for d in response.json()["error"]["details"]]


def mutate_calls(sim):
    return [r for r in sim.requests if r.url.path.endswith(":mutate")]


def campaign(sim, external):
    return next(
        r["campaign"] for r in sim.customers[AU].campaigns if r["campaign"].get("id") == external
    )


def budget_micros(sim):
    return sim.customers[AU].budgets[0]["campaignBudget"]["amountMicros"]


@pytest.fixture
def held(runtime):
    """Jobs are kept instead of run, so a test can run (or not run) each one itself."""
    jobs: list[uuid.UUID] = []
    runtime.enqueue_job = lambda job_id, delay=0: jobs.append(job_id)
    return jobs


def run(runtime, job_id):
    return run_job(runtime, job_id, HANDLERS)


# ------------------------------------------------------------------ end to end
def test_a_pause_is_checked_approved_sent_once_and_verified(org, gsim, admin_engine):
    preview = org.post(f"{org.base}/validate", body(org.search))
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    assert data["passed"] is True and data["dry_run"] == {"result": "passed", "reason": None}
    assert data["current"]["status"] == "active" and data["budget_limits"] is None
    assert [c["check"] for c in data["checks"]] == ["shape", "resource", "limits", "state"]
    dry = json.loads(mutate_calls(gsim)[-1].content)
    assert dry["validateOnly"] is True and gsim.mutations == []

    action = ask(org, org.search)
    assert action["status"] == "pending" and action["previous"]["status"] == "active"
    assert gsim.mutations == [] and campaign(gsim, "11")["status"] == "ENABLED"

    done = org.post(f"{org.base}/{action['id']}/approve")
    assert done.status_code == 200, done.text
    result = done.json()["data"]
    assert (result["status"], result["verification"]) == ("succeeded", "verified")
    assert campaign(gsim, "11")["status"] == "PAUSED"
    assert gsim.mutations == [{"resources": "campaigns", "status": "PAUSED"}]
    sent = [json.loads(r.content) for r in mutate_calls(gsim)]
    assert [s["validateOnly"] for s in sent] == [True, True, False]  # validate, request, send
    assert result["platform_request"]["operations"][0]["updateMask"] == "status"
    assert "Bearer" not in json.dumps(result) and "ya29" not in json.dumps(result)
    assert [(e["from_status"], e["status"]) for e in result["events"]] == [
        (None, "pending"),
        ("pending", "approved"),
        ("approved", "queued"),
        ("queued", "submitting"),
        ("submitting", "succeeded"),
    ]
    assert result["observed"]["status"] == "paused" and result["can_undo"] is True
    (local,) = rows(admin_engine, "SELECT status FROM ad_campaigns WHERE id = :i", i=org.search)
    assert local["status"] == "paused"  # AdVegaX's copy follows what the platform reported
    audit = [
        r["action"]
        for r in rows(
            admin_engine,
            "SELECT action FROM audit_logs WHERE resource_type = 'action' ORDER BY created_at",
        )
    ]
    assert audit == [
        "action.requested",
        "action.approved",
        "action.queued",
        "action.submitting",
        "action.succeeded",
        "action.verified",
    ]


def test_resume_and_state_checks(org, gsim):
    paused = org.post(org.base, body(org.pmax))
    assert paused.status_code == 422
    assert paused.json()["error"]["code"] == "ACTION_INVALID"
    assert reasons(paused) == ["already_paused"]
    resumed = ask(org, org.pmax, "campaign.resume")
    org.post(f"{org.base}/{resumed['id']}/approve")
    assert campaign(gsim, "12")["status"] == "ENABLED"
    again = org.post(org.base, body(org.pmax, "campaign.resume"))
    assert reasons(again) == ["already_active"]


# ------------------------------------------------------------------ budgets
def test_a_daily_budget_change_within_the_limits(org, gsim):
    preview = org.post(
        f"{org.base}/validate", body(org.search, "campaign.set_daily_budget", daily_budget="60")
    ).json()["data"]
    assert preview["passed"] is True
    assert preview["budget_limits"] == {
        "lowest": "5.00",  # 90 % down
        "highest": "75.00",  # 50 % up
        "platform_minimum": "1.60",
        "organization_maximum": "500.00",
        "increase_percent": 50,
        "decrease_percent": 90,
    }
    action = ask(org, org.search, "campaign.set_daily_budget", daily_budget="60")
    assert action["params"] == {"daily_budget": "60.00"}
    result = org.post(f"{org.base}/{action['id']}/approve").json()["data"]
    assert (result["status"], result["verification"]) == ("succeeded", "verified")
    assert budget_micros(gsim) == "60000000"
    update = result["platform_request"]["operations"][0]
    assert update["updateMask"] == "amountMicros" and update["update"]["amountMicros"] == "60000000"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("80", ["increase_too_large"]),
        ("4", ["decrease_too_large"]),
        ("50", ["no_change"]),
        ("60.001", ["daily_budget_precision"]),
        ("-3", ["daily_budget_invalid"]),
        ("abc", ["daily_budget_invalid"]),
    ],
)
def test_budget_limits(org, amount, expected):
    response = org.post(
        org.base, body(org.search, "campaign.set_daily_budget", daily_budget=amount)
    )
    assert response.status_code == 422
    assert reasons(response) == expected


def test_the_minimum_and_maximum(org, runtime):
    enable(runtime, ACTIONS_MAX_DECREASE_PERCENT=99)
    low = org.post(org.base, body(org.search, "campaign.set_daily_budget", daily_budget="1.50"))
    assert reasons(low) == ["below_platform_minimum"]
    org.put(
        org.settings_url,
        {"paused": False, "require_second_person": False, "max_daily_budget": "55.00"},
    )
    high = org.post(org.base, body(org.search, "campaign.set_daily_budget", daily_budget="60"))
    assert reasons(high) == ["above_maximum"]
    org.put(org.settings_url, {"paused": False, "require_second_person": False})
    unset = org.post(org.base, body(org.search, "campaign.set_daily_budget", daily_budget="52"))
    assert reasons(unset) == ["maximum_not_set"]  # required before the first budget change


def test_shared_and_lifetime_budgets_are_refused(org, gsim, admin_engine):
    lifetime = org.post(org.base, body(org.pmax, "campaign.set_daily_budget", daily_budget="20"))
    assert reasons(lifetime) == ["budget_not_daily"]
    gsim.customers[AU].budgets[0]["campaignBudget"]["explicitlyShared"] = True
    shared = org.post(org.base, body(org.search, "campaign.set_daily_budget", daily_budget="52"))
    assert reasons(shared) == ["budget_shared"]  # it would change the other campaigns too


def test_one_budget_change_per_campaign_per_hour(org, clock):
    first = ask(org, org.search, "campaign.set_daily_budget", daily_budget="55")
    org.post(f"{org.base}/{first['id']}/approve")
    again = org.post(org.base, body(org.search, "campaign.set_daily_budget", daily_budget="58"))
    assert reasons(again) == ["budget_changed_recently"]
    clock.advance(timedelta(minutes=61))
    later = ask(org, org.search, "campaign.set_daily_budget", daily_budget="58")
    assert later["status"] == "pending"


def test_changes_per_account_per_day(org, runtime):
    enable(runtime, ACTIONS_DAILY_LIMIT_PER_ACCOUNT=1)
    first = ask(org, org.search)
    org.post(f"{org.base}/{first['id']}/approve")
    second = org.post(org.base, body(org.pmax, "campaign.resume"))
    assert reasons(second) == ["daily_limit_reached"]


# ------------------------------------------------------------------ duplicates, decisions
def test_duplicates_and_one_open_change_per_campaign(org):
    ask(org, org.search)
    twice = org.post(org.base, body(org.search))
    assert (twice.status_code, twice.json()["error"]["code"]) == (409, "ACTION_DUPLICATE")
    other = org.post(org.base, body(org.search, "campaign.set_daily_budget", daily_budget="55"))
    assert reasons(other) == ["campaign_has_open_change"]


def test_roles_and_the_second_person_rule(org, make_client):
    manager, analyst, viewer, admin = make_client(), make_client(), make_client(), make_client()
    for client, role in ((manager, "manager"), (analyst, "analyst"), (viewer, "viewer")):
        email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
        client.signup(email)
        org.invite_and_join(org.org, client, email, role)
    email = f"admin-{uuid.uuid4().hex[:6]}@example.com"
    admin.signup(email)
    org.invite_and_join(org.org, admin, email, "admin")
    assert analyst.post(org.base, body(org.search)).status_code == 403
    assert viewer.post(f"{org.base}/validate", body(org.search)).status_code == 403
    action = manager.post(org.base, body(org.search)).json()["data"]
    assert viewer.get(f"{org.base}/{action['id']}").status_code == 200
    assert manager.post(f"{org.base}/{action['id']}/approve").status_code == 403
    assert manager.put(org.access, {"allowed": False}).status_code == 403
    assert (
        manager.put(org.settings_url, {"paused": True, "require_second_person": False}).status_code
        == 403
    )

    org.put(
        org.settings_url,
        {"paused": False, "require_second_person": True, "max_daily_budget": "500"},
    )
    mine = org.post(org.base, body(org.pmax, "campaign.resume")).json()["data"]
    refused = org.post(f"{org.base}/{mine['id']}/approve")
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "SECOND_PERSON_REQUIRED")
    assert admin.post(f"{org.base}/{mine['id']}/approve").json()["data"]["status"] == "succeeded"
    assert org.post(f"{org.base}/{action['id']}/approve").json()["data"]["status"] == "succeeded"


def test_reject_needs_a_reason_and_cancel(org, make_client, gsim):
    action = ask(org, org.search)
    assert org.post(f"{org.base}/{action['id']}/reject", {"reason": ""}).status_code == 422
    rejected = org.post(f"{org.base}/{action['id']}/reject", {"reason": "Not during the sale"})
    assert rejected.json()["data"]["status"] == "rejected"
    assert rejected.json()["data"]["decision_reason"] == "Not during the sale"
    assert org.post(f"{org.base}/{action['id']}/approve").status_code == 409

    manager = make_client()
    email = f"manager-{uuid.uuid4().hex[:6]}@example.com"
    manager.signup(email)
    org.invite_and_join(org.org, manager, email, "manager")
    other = ask(org, org.search)
    assert manager.post(f"{org.base}/{other['id']}/cancel").status_code == 403  # not theirs
    cancelled = org.post(f"{org.base}/{other['id']}/cancel").json()["data"]
    assert cancelled["status"] == "cancelled" and gsim.mutations == []


def test_a_request_not_decided_in_time_is_stale(org, clock, runtime):
    enable(runtime, ACTIONS_PENDING_TTL=timedelta(minutes=30))  # sessions outlive it here
    action = ask(org, org.search)
    clock.advance(timedelta(minutes=31))
    late = org.post(f"{org.base}/{action['id']}/approve")
    assert (late.status_code, late.json()["error"]["code"]) == (409, "ACTION_STALE")
    assert org.get(f"{org.base}/{action['id']}").json()["data"]["status"] == "stale"


# ------------------------------------------------------------------ switches and access
def test_the_installation_switch(org, runtime):
    runtime.settings = runtime.settings.model_copy(update={"ACTIONS_ENABLED": False})
    off = org.post(f"{org.base}/validate", body(org.search))
    assert (off.status_code, off.json()["error"]["code"]) == (409, "ACTIONS_DISABLED")
    assert org.post(org.base, body(org.search)).status_code == 409
    settings = org.get(org.settings_url).json()["data"]
    assert settings["engine_enabled"] is False


def test_pause_all_changes_holds_queued_changes(org, gsim, held, runtime):
    action = ask(org, org.search)
    org.post(f"{org.base}/{action['id']}/approve")
    org.put(
        org.settings_url,
        {"paused": True, "require_second_person": False, "max_daily_budget": "500"},
    )
    assert run(runtime, held.pop()) is JobOutcome.SUCCEEDED
    assert org.get(f"{org.base}/{action['id']}").json()["data"]["status"] == "queued"
    assert gsim.mutations == []
    refused = org.post(org.base, body(org.pmax, "campaign.resume"))
    assert refused.json()["error"]["code"] == "ACTIONS_DISABLED"
    org.put(
        org.settings_url,
        {"paused": False, "require_second_person": False, "max_daily_budget": "500"},
    )
    assert len(held) == 1  # lifting the pause sends what was queued
    run(runtime, held.pop())
    assert org.get(f"{org.base}/{action['id']}").json()["data"]["status"] == "succeeded"


def test_changes_must_be_allowed_for_the_connection(org, admin_engine):
    access = org.get(org.access).json()["data"]
    assert access == {
        "connection_id": org.conn,
        "provider": "google_ads",
        "supported": True,
        "allowed": True,
        "allowed_at": access["allowed_at"],
        "allowed_by": access["allowed_by"],
        "missing_permissions": [],
        "can_request_permission": False,
    }
    pending = ask(org, org.search)
    assert org.put(org.access, {"allowed": False}).json()["data"]["allowed"] is False
    refused = org.post(org.base, body(org.pmax, "campaign.resume"))
    assert refused.json()["error"]["code"] == "ACTION_NOT_ALLOWED"
    assert reasons(refused) == ["changes_not_allowed"]
    late = org.post(f"{org.base}/{pending['id']}/approve")
    assert late.json()["error"]["code"] == "ACTION_NOT_ALLOWED"
    audit = rows(
        admin_engine,
        "SELECT action FROM audit_logs WHERE resource_type = 'connection' "
        "AND action LIKE 'connection.write_access%' ORDER BY created_at",
    )
    assert [a["action"] for a in audit] == [
        "connection.write_access_granted",
        "connection.write_access_removed",
    ]


# ------------------------------------------------------------------ the worker
def test_a_campaign_changed_since_the_request_stops_as_stale(org, gsim, held, runtime):
    action = ask(org, org.search, "campaign.set_daily_budget", daily_budget="60")
    org.post(f"{org.base}/{action['id']}/approve")
    gsim.customers[AU].budgets[0]["campaignBudget"]["amountMicros"] = "45000000"  # someone else
    run(runtime, held.pop())
    data = org.get(f"{org.base}/{action['id']}").json()["data"]
    assert (data["status"], data["error_code"]) == ("stale", "campaign_changed")
    assert data["observed"]["daily_budget"] == "45.00"
    assert gsim.mutations == [] and budget_micros(gsim) == "45000000"


def test_a_lost_answer_is_looked_up_never_sent_again(org, gsim, held, runtime):
    action = ask(org, org.search)
    org.post(f"{org.base}/{action['id']}/approve")
    gsim.change_outcomes = ["lose_answer"]
    run(runtime, held.pop())
    data = org.get(f"{org.base}/{action['id']}").json()["data"]
    assert (data["status"], data["error_code"]) == ("unknown", "outcome_unknown")
    assert len(gsim.mutations) == 1 and len(held) == 1  # a look-up is scheduled, not a resend
    sends = len([r for r in mutate_calls(gsim) if not json.loads(r.content)["validateOnly"]])
    run(runtime, held.pop())
    data = org.get(f"{org.base}/{action['id']}").json()["data"]
    assert (data["status"], data["verification"]) == ("succeeded", "verified")
    assert (
        len([r for r in mutate_calls(gsim) if not json.loads(r.content)["validateOnly"]]) == sends
    )
    assert data["events"][-1]["detail"] == {"found_by": "look_up"}


def test_a_timeout_before_the_change_is_found_not_applied(org, gsim, held, runtime):
    action = ask(org, org.search)
    org.post(f"{org.base}/{action['id']}/approve")
    gsim.change_outcomes = ["timeout"]
    run(runtime, held.pop())
    run(runtime, held.pop())
    data = org.get(f"{org.base}/{action['id']}").json()["data"]
    assert (data["status"], data["error_code"]) == ("failed", "not_applied")
    assert gsim.mutations == [] and campaign(gsim, "11")["status"] == "ENABLED"
    again = ask(org, org.search)  # safe to request again
    assert again["status"] == "pending"


def test_an_unreadable_outcome_is_looked_up_a_bounded_number_of_times(org, gsim, held, runtime):
    enable(runtime, ACTIONS_RECONCILE_ATTEMPTS=2)
    action = ask(org, org.search)
    org.post(f"{org.base}/{action['id']}/approve")
    gsim.change_outcomes = ["server_error"]
    run(runtime, held.pop())
    gsim.fail_next = [(500, {"internalError": "INTERNAL_ERROR"})] * 2
    run(runtime, held.pop())  # cannot read: looked up again later
    assert len(held) == 1
    run(runtime, held.pop())
    data = org.get(f"{org.base}/{action['id']}").json()["data"]
    assert (data["status"], data["error_code"]) == ("unknown", "needs_checking")
    assert held == [] and gsim.mutations == []


def test_a_platform_refusal_fails_the_change(org, gsim, held, runtime):
    action = ask(org, org.search)
    org.post(f"{org.base}/{action['id']}/approve")
    gsim.change_outcomes = ["refuse"]
    run(runtime, held.pop())
    data = org.get(f"{org.base}/{action['id']}").json()["data"]
    assert (data["status"], data["error_code"]) == ("failed", "invalid_request")
    assert data["events"][-1]["detail"] == {"reason": "invalid_request", "sent": True}


def test_a_mismatch_is_reported(org, gsim, held, runtime):
    action = ask(org, org.search)
    org.post(f"{org.base}/{action['id']}/approve")
    gsim.change_outcomes = ["ignore"]
    run(runtime, held.pop())
    data = org.get(f"{org.base}/{action['id']}").json()["data"]
    assert (data["status"], data["verification"]) == ("succeeded", "mismatch")
    assert data["can_undo"] is False


def test_two_workers_send_a_change_once(org, gsim, held, runtime, admin_engine):
    action = ask(org, org.search)
    org.post(f"{org.base}/{action['id']}/approve")
    job = held.pop()
    assert run(runtime, job) is JobOutcome.SUCCEEDED
    assert run(runtime, job) is JobOutcome.SKIPPED  # the same message delivered twice
    with admin_engine.begin() as db:  # a second job for the same change
        db.execute(
            text(
                "INSERT INTO job_runs (id, organization_id, job_type, status, subject_type, "
                "subject_id, attempts, max_attempts) VALUES (:i, :o, 'action_execute', 'queued', "
                "'action', :s, 0, 3)"
            ),
            {"i": (second := uuid.uuid4()), "o": org.org, "s": action["id"]},
        )
    assert run(runtime, second) is JobOutcome.SUCCEEDED  # finds it no longer queued
    assert len(gsim.mutations) == 1


def test_a_campaign_being_changed_makes_the_job_wait(org, gsim, held, runtime):
    action = ask(org, org.search)
    org.post(f"{org.base}/{action['id']}/approve")
    with account_lock(runtime.redis, f"action-campaign:{org.search}", wait_seconds=0):
        assert run(runtime, held.pop()) is JobOutcome.RETRY
    assert org.get(f"{org.base}/{action['id']}").json()["data"]["status"] == "queued"
    assert gsim.mutations == []


def test_the_sweep(org, gsim, held, runtime, admin_engine, clock):
    action = ask(org, org.search)
    org.post(f"{org.base}/{action['id']}/approve")
    held.clear()  # the message was lost
    assert engine.sweep(runtime) == 0  # not long enough ago
    clock.advance(runtime.settings.SCHEDULE_ACTIONS_SWEEP_INTERVAL + timedelta(seconds=1))
    assert engine.sweep(runtime) == 1
    run(runtime, held.pop())
    assert org.get(f"{org.base}/{action['id']}").json()["data"]["status"] == "succeeded"

    stuck = ask(org, org.pmax, "campaign.resume")
    with admin_engine.begin() as db:  # a worker stopped right after writing "submitting"
        db.execute(
            text("UPDATE actions SET status = 'submitting', updated_at = :t WHERE id = :i"),
            {"i": stuck["id"], "t": clock.now()},
        )
    clock.advance(runtime.settings.ACTIONS_LOCK_TTL + timedelta(seconds=1))
    assert engine.sweep(runtime) == 1
    run(runtime, held.pop())  # looked up: still paused, so it was not applied
    data = org.get(f"{org.base}/{stuck['id']}").json()["data"]
    assert (data["status"], data["error_code"]) == ("failed", "not_applied")


# ------------------------------------------------------------------ undo
def test_undo_is_another_approved_change(org, gsim):
    first = ask(org, org.search, "campaign.set_daily_budget", daily_budget="70")
    org.post(f"{org.base}/{first['id']}/approve")
    undo = org.post(f"{org.base}/{first['id']}/undo")
    assert undo.status_code == 201, undo.text
    back = undo.json()["data"]
    assert (back["status"], back["undo_of"], back["params"]) == (
        "pending",
        first["id"],
        {"daily_budget": "50.00"},
    )  # within the hour and below the step limit: an undo restores an earlier value
    assert org.post(f"{org.base}/{first['id']}/undo").status_code == 409  # once
    org.post(f"{org.base}/{back['id']}/approve")
    assert budget_micros(gsim) == "50000000"
    assert org.get(f"{org.base}/{first['id']}").json()["data"]["can_undo"] is False


def test_lists_and_tenants(org, make_client):
    action = ask(org, org.search)
    listed = org.get(f"{org.base}?status=open").json()
    assert [a["id"] for a in listed["data"]] == [action["id"]]
    assert org.get(f"{org.base}?status=succeeded").json()["data"] == []
    assert org.get(f"{org.base}?campaign_id={org.pmax}").json()["data"] == []
    other = make_client()
    other.signup(f"other-{uuid.uuid4().hex[:6]}@example.com")
    other_org = other.create_org("Other")["id"]
    assert other.get(f"/organizations/{other_org}/actions/{action['id']}").status_code == 404
    assert other.post(f"/organizations/{other_org}/actions", body(org.search)).status_code == 404
