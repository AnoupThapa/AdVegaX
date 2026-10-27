"""Controlled autopilot against the Google Ads simulator (Phase 12, tasks 12-02 … 12-07).

The organization and figures of ``test_recommendations_api`` (Google Ads test account, Search
campaign 11 active with its own AUD 50.00 daily budget; changes allowed; maximum AUD 500.00).
The installation switch and allow-list are set per test; readiness (5 verified changes from
approved advice) is given by a stand-in unless a test checks it.

Covers PLAN §8 and §10: the gate and readiness, owners only and the typed confirmation, the
policy and its ceilings, automatic pause and budget cut through the Action Engine with the
policy kept, never an increase, every limit (account, exclusion, age, cooldown, per-change and
cumulative cut, the day limit), Stop and "Pause all changes", self-stop on a refused or
mismatched change and on the day limit reached twice, emails, roles and the runs.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from app.domains.autopilot import policy as autopilot_policy
from app.domains.optimization import look
from app.domains.optimization.signals import Margin

from tests.api.test_actions_api import AU, gsim, org, rows  # noqa: F401  (fixtures)
from tests.api.test_recommendations_api import (
    NO_RESULTS,
    TODAY,
    _exec,
    figures,
    member,
    open_items,
    recs,  # noqa: F401  (fixture)
    refresh,
    wait,
)

LIMITS = {
    "max_changes_per_day": 5,
    "campaign_cooldown_days": 7,
    "max_decrease_percent": 20,
    "max_cumulative_decrease_percent": 50,
    "cumulative_window_days": 30,
    "min_campaign_age_days": 14,
}
MARGIN = Margin(Decimal("0.4"), Decimal(1), None)


@pytest.fixture
def ap(recs, runtime, monkeypatch, admin_engine):  # noqa: F811
    c = recs
    runtime.settings = runtime.settings.model_copy(
        update={"AUTOPILOT_ENABLED": True, "AUTOPILOT_ORGANIZATIONS": [uuid.UUID(c.org)]}
    )
    monkeypatch.setattr(autopilot_policy, "proven", lambda session, org_id: (5, 0))
    c.ap = f"/organizations/{c.org}/autopilot"
    (account,) = rows(
        admin_engine, "SELECT id FROM ad_accounts WHERE external_account_id = :e", e=AU
    )
    c.account = str(account["id"])
    return c


def policy(c, **changes):
    body = {
        "kinds": ["spend_without_results", "losing_money"],
        "ad_account_ids": [c.account],
        "excluded_campaign_ids": [],
        **LIMITS,
        **changes,
    }
    response = c.put(c.ap, body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def enable(c):
    response = c.post(f"{c.ap}/enable", {"confirm": "Eve Zone"})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def automatic(admin_engine):
    return rows(
        admin_engine,
        "SELECT id, action_type, status, params, policy, recommendation_id FROM actions "
        "WHERE source = 'autopilot' ORDER BY created_at",
    )


def emails(admin_engine, template):
    return rows(admin_engine, "SELECT recipient FROM email_outbox WHERE template = :t", t=template)


# ------------------------------------------------------------------ switching on
def test_off_by_default_and_ready_only_after_verified_changes(recs, runtime, admin_engine):  # noqa: F811
    ap = f"/organizations/{recs.org}/autopilot"
    shown = recs.get(ap).json()["data"]
    assert shown["enabled"] is False
    assert shown["readiness"]["missing"] == [
        "installation_off",
        "not_in_rollout",
        "too_few_verified_changes",
    ]
    assert shown["ceilings"]["max_changes_per_day"] == 5
    runtime.settings = runtime.settings.model_copy(
        update={
            "AUTOPILOT_ENABLED": True,
            "AUTOPILOT_ORGANIZATIONS": [uuid.UUID(recs.org)],
            "AUTOPILOT_READY_CHANGES": 1,
        }
    )
    figures(admin_engine, recs.search, *NO_RESULTS)
    item = open_items(refresh(recs))[0]
    approved = recs.post(f"{recs.recs}/{item['id']}/approve")
    assert approved.status_code == 200, approved.text
    ready = recs.get(ap).json()["data"]["readiness"]
    assert (ready["ready"], ready["verified_changes"]) == (True, 1)
    _exec(admin_engine, "UPDATE actions SET verification = 'mismatch'")
    assert recs.get(ap).json()["data"]["readiness"]["missing"] == [
        "too_few_verified_changes",
        "mismatched_changes",
    ]


def test_only_owners_switch_it_on_with_the_name_typed(ap, make_client):
    refused = ap.post(f"{ap.ap}/enable", {"confirm": "Eve Zone"})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "AUTOPILOT_NOT_READY"
    assert {d["reason"] for d in refused.json()["error"]["details"]} == {"no_ad_accounts"}
    policy(ap)
    wrong = ap.post(f"{ap.ap}/enable", {"confirm": "eve zone!"})
    assert wrong.json()["error"]["code"] == "AUTOPILOT_CONFIRMATION"
    admin = member(make_client, ap, "admin")
    assert admin.post(f"{ap.ap}/enable", {"confirm": "Eve Zone"}).status_code == 403
    assert admin.put(ap.ap, {}).status_code in (403, 422)
    on = enable(ap)
    assert on["enabled"] is True and on["enabled_by"] is not None
    manager = member(make_client, ap, "manager")
    off = manager.post(f"{ap.ap}/stop").json()["data"]
    assert (off["enabled"], off["stopped_reason"]) == (False, "stopped")
    analyst = member(make_client, ap, "analyst")
    assert analyst.post(f"{ap.ap}/stop").status_code == 403
    assert analyst.get(ap.ap).status_code == 200


def test_limits_cannot_be_looser_than_the_installation_allows(ap, admin_engine):
    for name, value in (
        ("max_changes_per_day", 6),
        ("max_decrease_percent", 30),
        ("campaign_cooldown_days", 3),
        ("min_campaign_age_days", 7),
    ):
        body = {
            "kinds": [],
            "ad_account_ids": [],
            "excluded_campaign_ids": [],
            **LIMITS,
            name: value,
        }
        refused = ap.put(ap.ap, body)
        assert refused.status_code == 422, name
        assert refused.json()["error"]["details"][0]["field"] == name
    other = {
        "kinds": [],
        "ad_account_ids": [str(uuid.uuid4())],
        "excluded_campaign_ids": [],
        **LIMITS,
    }
    assert ap.put(ap.ap, other).json()["error"]["details"] == [{"reason": "not_this_organization"}]
    stricter = policy(ap, max_changes_per_day=2, min_campaign_age_days=30)
    assert (stricter["max_changes_per_day"], stricter["min_campaign_age_days"]) == (2, 30)


# ------------------------------------------------------------------ acting
def test_autopilot_pauses_a_campaign_spending_without_results(ap, gsim, admin_engine):  # noqa: F811
    policy(ap)
    enable(ap)
    figures(admin_engine, ap.search, *NO_RESULTS)
    data = refresh(ap)
    assert open_items(data) == []  # acted on
    (made,) = automatic(admin_engine)
    assert (made["action_type"], made["status"]) == ("campaign.pause", "succeeded")
    assert made["policy"]["max_changes_per_day"] == 5 and made["policy"]["enabled_by"]
    campaign = next(r for r in gsim.customers[AU].campaigns if r["campaign"]["id"] == "11")
    assert campaign["campaign"]["status"] == "PAUSED"
    rec = ap.get(f"{ap.recs}/{made['recommendation_id']}").json()["data"]
    assert rec["status"] == "approved" and rec["action"]["status"] == "succeeded"
    change = ap.get(f"/organizations/{ap.org}/actions/{made['id']}").json()["data"]
    assert change["source"] == "autopilot" and change["can_undo"] is True
    (run,) = ap.get(f"{ap.ap}/runs").json()["data"]
    assert run["made"] == [str(made["id"])] and run["stopped_reason"] is None
    assert len(emails(admin_engine, "autopilot_changes")) == 1
    audit = rows(admin_engine, "SELECT action FROM audit_logs WHERE actor_type = 'autopilot'")
    assert {"action.requested", "recommendation.approved", "autopilot.run"} <= {
        a["action"] for a in audit
    }


def test_autopilot_lowers_a_money_losing_budget_and_never_raises_one(
    ap,
    gsim,  # noqa: F811
    admin_engine,
    monkeypatch,
):
    monkeypatch.setattr(look, "_margin", lambda *a: MARGIN)
    policy(ap)
    enable(ap)
    figures(admin_engine, ap.search, (50, 5, 200), (40, 4, 160))  # held back: an increase
    held = open_items(refresh(ap), "budget_limited")[0]
    assert automatic(admin_engine) == []
    (run,) = ap.get(f"{ap.ap}/runs").json()["data"]
    assert {"recommendation_id": held["id"], "reason": "kind_not_allowed"} in run["skipped"]

    figures(admin_engine, ap.search, (20, 2, 40), (20, 2, 40))  # losing money: a cut
    refresh(ap)
    (made,) = automatic(admin_engine)
    assert made["params"] == {"daily_budget": "40.00"} and made["status"] == "succeeded"
    assert gsim.customers[AU].budgets[0]["campaignBudget"]["amountMicros"] == "40000000"


def test_limits_leave_advice_to_a_person(ap, admin_engine, monkeypatch, runtime):
    monkeypatch.setattr(look, "_margin", lambda *a: MARGIN)
    runtime.settings = runtime.settings.model_copy(update={"OPTIMIZATION_REFRESHES_PER_DAY": 10})
    figures(admin_engine, ap.search, (20, 2, 40), (20, 2, 40))
    policy(ap, max_decrease_percent=10)
    enable(ap)
    item = open_items(refresh(ap), "losing_money")[0]
    assert automatic(admin_engine) == []
    reasons = {s["reason"] for s in ap.get(f"{ap.ap}/runs").json()["data"][0]["skipped"]}
    assert "decrease_too_large" in reasons
    assert ap.get(f"{ap.recs}/{item['id']}").json()["data"]["status"] == "open"

    for changes, reason in (
        ({"excluded_campaign_ids": [ap.search]}, "campaign_excluded"),
        ({"ad_account_ids": []}, "account_not_included"),
        ({"kinds": ["spend_without_results"]}, "kind_not_allowed"),
        ({"min_campaign_age_days": 60}, "campaign_too_new"),
    ):
        if reason == "campaign_too_new":  # it started 30 days ago
            _exec(
                admin_engine,
                "UPDATE ad_campaigns SET start_date = :d WHERE id = :c",
                d=TODAY - timedelta(days=30),
                c=ap.search,
            )
        policy(ap, **changes)
        refresh(ap)
        latest = ap.get(f"{ap.ap}/runs").json()["data"][0]
        assert reason in {s["reason"] for s in latest["skipped"]}, reason


def test_cooldown_and_cumulative_cut(ap, admin_engine, monkeypatch, clock):
    monkeypatch.setattr(look, "_margin", lambda *a: MARGIN)
    policy(ap, max_cumulative_decrease_percent=30, campaign_cooldown_days=7)
    enable(ap)
    figures(admin_engine, ap.search, (20, 2, 40), (20, 2, 40))
    refresh(ap)
    assert [a["params"] for a in automatic(admin_engine)] == [{"daily_budget": "40.00"}]
    wait(ap, clock, 8 * 24)
    later = TODAY + timedelta(days=8)
    figures(admin_engine, ap.search, (20, 2, 40), (20, 2, 40), from_day=later)
    refresh(ap)  # 40 → 32 would be a 36 % cut from 50 in 30 days
    assert len(automatic(admin_engine)) == 1
    latest = ap.get(f"{ap.ap}/runs").json()["data"][0]
    assert "cumulative_limit" in {s["reason"] for s in latest["skipped"]}
    policy(ap, max_cumulative_decrease_percent=30, campaign_cooldown_days=14)
    refresh(ap)
    latest = ap.get(f"{ap.ap}/runs").json()["data"][0]
    assert "campaign_cooldown" in {s["reason"] for s in latest["skipped"]}


# ------------------------------------------------------------------ stopping
def test_stop_and_pause_all_changes_stop_it(ap, admin_engine):
    policy(ap)
    enable(ap)
    ap.post(f"{ap.ap}/stop")
    figures(admin_engine, ap.search, *NO_RESULTS)
    assert len(open_items(refresh(ap))) == 1
    assert automatic(admin_engine) == []
    enable(ap)
    ap.put(
        f"/organizations/{ap.org}/action-settings",
        {"paused": True, "require_second_person": False, "max_daily_budget": "500.00"},
    )
    refresh(ap)
    assert automatic(admin_engine) == []
    assert "changes_switched_off" in ap.get(ap.ap).json()["data"]["readiness"]["missing"]


def test_it_stops_itself_when_a_change_is_refused_or_not_verified(
    ap,
    gsim,  # noqa: F811
    admin_engine,
):
    policy(ap)
    enable(ap)
    gsim.change_outcomes = ["refuse"]
    figures(admin_engine, ap.search, *NO_RESULTS)
    refresh(ap)
    (made,) = automatic(admin_engine)
    assert made["status"] == "failed"
    shown = ap.get(ap.ap).json()["data"]
    assert (shown["enabled"], shown["stopped_reason"]) == (False, "change_failed")
    assert len(emails(admin_engine, "autopilot_stopped")) == 1


def test_it_stops_itself_when_the_change_is_not_shown(ap, gsim, admin_engine):  # noqa: F811
    policy(ap)
    enable(ap)
    gsim.change_outcomes = ["ignore"]
    figures(admin_engine, ap.search, *NO_RESULTS)
    refresh(ap)
    shown = ap.get(ap.ap).json()["data"]
    assert (shown["enabled"], shown["stopped_reason"]) == (False, "not_verified")


def test_the_day_limit_reached_twice_stops_it(ap, admin_engine, clock):
    figures(admin_engine, ap.search, *NO_RESULTS)
    item = open_items(refresh(ap))[0]  # autopilot is not on yet: the advice stays open
    (campaign_12,) = rows(
        admin_engine, "SELECT id, ad_account_id FROM ad_campaigns WHERE external_campaign_id = '12'"
    )
    _exec(
        admin_engine,
        "INSERT INTO actions (id, organization_id, action_type, provider, ad_account_id, "
        "campaign_id, params, currency, previous, status, idempotency_key, checks, source, "
        "recommendation_id, policy, created_at, updated_at) VALUES (gen_random_uuid(), :org, "
        "'campaign.pause', 'google_ads', :acc, :cid, '{}', 'AUD', '{}', 'succeeded', 'x', '[]', "
        "'autopilot', :rec, '{}', now(), now())",
        org=ap.org,
        acc=campaign_12["ad_account_id"],
        cid=campaign_12["id"],
        rec=item["id"],
    )
    _exec(admin_engine, "UPDATE actions SET created_at = :t", t=clock.now())
    policy(ap, max_changes_per_day=1)
    enable(ap)
    refresh(ap)
    assert ap.get(ap.ap).json()["data"]["enabled"] is True
    refresh(ap)
    shown = ap.get(ap.ap).json()["data"]
    assert (shown["enabled"], shown["stopped_reason"]) == (False, "daily_limit_reached")
