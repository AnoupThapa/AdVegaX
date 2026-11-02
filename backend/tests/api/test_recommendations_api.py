"""Recommendations against the Google Ads simulator (Phase 11, tasks 11-05 … 11-08).

The linked Google Ads test account of ``test_actions_api`` (AUD, Sydney; Search campaign 11,
active, its own daily budget of AUD 50.00; changes allowed; maximum AUD 500.00). AdVegaX's
figures for campaign 11 are written as daily rows for the 35 days before the test day: the
recent 7 days and the 28 before them. The organization has no store, so the profit rules are
skipped unless a test gives a margin.

Covers PLAN §8 and §10: the daily look and "Look again now", Rules only and the AI simulator's
explanations (and a refused answer), approval into the Action Engine (sent at once by an
owner, waiting for a manager or the second person), out of date, expiry, rejection and the
quiet period, "looked into", budget advice, outcomes, the scheduler, settings and roles.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from app.domains.optimization import look
from app.domains.optimization.signals import Margin
from sqlalchemy import text

from tests.ai_sim import AiSim
from tests.api.test_actions_api import AU, gsim, org, rows  # noqa: F401  (fixtures)

TODAY = date(2026, 10, 14)  # the test clock's day in Sydney


def _exec(admin_engine, sql, **params):
    with admin_engine.begin() as db:
        db.execute(text(sql), params)


def figures(admin_engine, campaign, recent, baseline, *, from_day=TODAY):
    """Daily rows: ``recent`` = (cost, conversions, value) for each of the 7 days before
    ``from_day``; ``baseline`` likewise for the 28 days before those."""
    _exec(
        admin_engine,
        "UPDATE ad_accounts SET history_from = '2026-08-01T00:00:00+00' "
        "WHERE external_account_id = :e",
        e=AU,
    )
    _exec(admin_engine, "DELETE FROM ad_performance_daily WHERE campaign_id = :c", c=campaign)
    for back in range(1, 36):
        cost, conv, value = recent if back <= 7 else baseline
        _exec(
            admin_engine,
            "INSERT INTO ad_performance_daily (id, organization_id, ad_account_id, level, "
            "entity_key, campaign_id, day, impressions, clicks, cost, conversions, "
            "conversion_value, currency, fetched_at) SELECT gen_random_uuid(), organization_id, "
            "ad_account_id, 'campaign', external_campaign_id, id, :day, 100, 20, :cost, :conv, "
            ":value, 'AUD', now() FROM ad_campaigns WHERE id = :c",
            c=campaign,
            day=from_day - timedelta(days=back),
            cost=Decimal(str(cost)),
            conv=Decimal(str(conv)),
            value=Decimal(str(value)),
        )


@pytest.fixture
def recs(org, admin_engine):  # noqa: F811
    org.recs = f"/organizations/{org.org}/recommendations"
    org.opt = f"/organizations/{org.org}/optimization-settings"
    return org


def refresh(c):
    response = c.post(f"{c.recs}/refresh")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def open_items(data, kind=None):
    return [
        i for i in data["items"] if i["status"] == "open" and (kind is None or i["kind"] == kind)
    ]


NO_RESULTS = ((20, 0, 0), (10, 1, 30))  # AUD 140 in 7 days, no conversions


def wait(c, clock, hours):
    """Move the clock forward, staying signed in (sessions end after a day without use)."""
    while hours > 0:
        step = min(hours, 12)
        clock.advance(timedelta(hours=step))
        assert c.get("/auth/me").status_code == 200
        hours -= step


def member(make_client, owner, role):
    client = make_client()
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    client.signup(email)
    owner.invite_and_join(owner.org, client, email, role)
    return client


# ------------------------------------------------------------------ the look
def test_spend_without_results_is_found_and_explained_by_rules(recs, admin_engine):
    figures(admin_engine, recs.search, *NO_RESULTS)
    data = refresh(recs)
    (item,) = open_items(data)
    assert item["kind"] == "spend_without_results"
    assert item["campaign"]["name"] == "Gloves - Search"
    assert item["figures"]["spend"] == "AUD 140.00"
    assert item["proposal"] == {
        "action_type": "campaign.pause",
        "params": {},
        "currency": "AUD",
        "previous_daily_budget": None,
        "text": "Pause the campaign",
    }
    assert item["ready"] is True and item["explained_by"] == "rules"
    assert "spent AUD 140.00" in item["explanation"] and item["risks"]
    summary = data["summary"]
    assert summary["open"] == 1 and summary["refreshes_left"] == 2
    assert summary["last_run"]["profit_rules"] == "skipped"
    assert summary["last_run"]["profit_reason"] == "no_store"
    assert summary["last_run"]["ai_problem"] == "ai_unavailable"
    audit = rows(
        admin_engine,
        "SELECT actor_type FROM audit_logs WHERE action = 'recommendation.created'",
    )
    assert [a["actor_type"] for a in audit] == ["system"]


def test_small_or_healthy_figures_give_no_advice(recs, admin_engine):
    figures(admin_engine, recs.search, (5, 0, 0), (5, 1, 30))  # AUD 35 < AUD 50
    assert open_items(refresh(recs)) == []
    figures(admin_engine, recs.search, (20, 2, 100), (20, 2, 100))
    assert open_items(refresh(recs)) == []


def test_a_new_look_replaces_the_open_advice(recs, admin_engine):
    figures(admin_engine, recs.search, *NO_RESULTS)
    first = open_items(refresh(recs))[0]
    second = open_items(refresh(recs))[0]
    assert first["id"] != second["id"]
    old = recs.get(f"{recs.recs}/{first['id']}").json()["data"]
    assert (old["status"], old["closed_reason"]) == ("superseded", "replaced")
    assert recs.post(f"{recs.recs}/{first['id']}/approve").json()["error"]["code"] == (
        "RECOMMENDATION_CLOSED"
    )


def test_the_ai_explains_and_ranks(recs, runtime, admin_engine):
    runtime.settings = runtime.settings.model_copy(update={"AI_ENABLED": True})
    sim = AiSim()
    runtime.extras["ai_adapter"] = sim.adapter()
    sim.queue(
        {
            "items": [
                {
                    "id": "c1",
                    "rank": 1,
                    "explanation": "AUD 140.00 spent in 7 days without one conversion.",
                    "confidence": "high",
                    "assumptions": ["Tracking works."],
                    "risks": ["Late conversions."],
                }
            ]
        }
    )
    figures(admin_engine, recs.search, *NO_RESULTS)
    data = refresh(recs)
    (item,) = open_items(data)
    assert (item["explained_by"], item["confidence"]) == ("ai", "high")
    assert item["explanation"].startswith("AUD 140.00 spent")
    assert item["ai_run_id"] is not None
    (run,) = rows(admin_engine, "SELECT task, context_snapshot FROM ai_runs")
    assert run["task"] == "optimization"
    assert "Gloves" not in str(run["context_snapshot"])  # no campaign names sent

    invented = {"items": [{**sim_answer(), "explanation": "It will earn AUD 9,999."}]}
    sim.queue(invented, invented)
    item = open_items(refresh(recs))[0]
    assert item["explained_by"] == "rules"
    assert recs.get(recs.recs).json()["data"]["summary"]["last_run"]["ai_problem"] == (
        "ai_answer_rejected"
    )


def sim_answer():
    return {
        "id": "c1",
        "rank": 1,
        "explanation": "x",
        "confidence": "low",
        "assumptions": [],
        "risks": [],
    }


# ------------------------------------------------------------------ approving
def test_an_owner_s_approval_sends_the_change(recs, gsim, admin_engine):  # noqa: F811
    figures(admin_engine, recs.search, *NO_RESULTS)
    item = open_items(refresh(recs))[0]
    response = recs.post(f"{recs.recs}/{item['id']}/approve")
    assert response.status_code == 200, response.text
    done = response.json()["data"]
    assert done["status"] == "approved" and done["action"]["status"] == "succeeded"
    action = recs.get(f"/organizations/{recs.org}/actions/{done['action']['id']}").json()["data"]
    assert (action["source"], action["recommendation_id"]) == ("recommendation", item["id"])
    assert action["action_type"] == "campaign.pause"
    campaign = next(r for r in gsim.customers[AU].campaigns if r["campaign"]["id"] == "11")
    assert campaign["campaign"]["status"] == "PAUSED"
    (audit,) = rows(
        admin_engine,
        "SELECT metadata FROM audit_logs WHERE action = 'recommendation.approved'",
    )
    assert audit["metadata"]["sent"] is True
    again = recs.post(f"{recs.recs}/{item['id']}/approve")
    assert again.json()["error"]["code"] == "RECOMMENDATION_CLOSED"


def test_a_manager_s_approval_waits_and_so_does_the_second_person(recs, make_client, admin_engine):
    figures(admin_engine, recs.search, *NO_RESULTS)
    item = open_items(refresh(recs))[0]
    manager = member(make_client, recs, "manager")
    analyst = member(make_client, recs, "analyst")
    assert analyst.get(recs.recs).status_code == 200
    assert analyst.post(f"{recs.recs}/{item['id']}/approve").status_code == 403
    assert analyst.post(f"{recs.recs}/refresh").status_code == 403
    waiting = manager.post(f"{recs.recs}/{item['id']}/approve").json()["data"]
    assert waiting["status"] == "approved" and waiting["action"]["status"] == "pending"


def test_the_second_person_rule_keeps_the_change_waiting(recs, admin_engine):
    recs.put(
        f"/organizations/{recs.org}/action-settings",
        {"paused": False, "require_second_person": True, "max_daily_budget": "500.00"},
    )
    figures(admin_engine, recs.search, *NO_RESULTS)
    item = open_items(refresh(recs))[0]
    held = recs.post(f"{recs.recs}/{item['id']}/approve").json()["data"]
    assert held["action"]["status"] == "pending"  # another owner or admin approves it


def test_out_of_date_advice_sends_nothing(recs, admin_engine):
    figures(admin_engine, recs.search, *NO_RESULTS)
    item = open_items(refresh(recs))[0]
    _exec(admin_engine, "UPDATE ad_campaigns SET status = 'paused' WHERE id = :c", c=recs.search)
    refused = recs.post(f"{recs.recs}/{item['id']}/approve")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "RECOMMENDATION_OUT_OF_DATE"
    assert refused.json()["error"]["details"] == [{"reason": "campaign_changed"}]
    assert rows(admin_engine, "SELECT id FROM actions") == []

    _exec(admin_engine, "UPDATE ad_campaigns SET status = 'active' WHERE id = :c", c=recs.search)
    item = open_items(refresh(recs))[0]
    figures(admin_engine, recs.search, (20, 3, 90), (10, 1, 30))  # conversions came in
    refused = recs.post(f"{recs.recs}/{item['id']}/approve")
    assert refused.json()["error"]["details"] == [{"reason": "no_longer_true"}]
    shown = recs.get(f"{recs.recs}/{item['id']}").json()["data"]
    assert (shown["status"], shown["closed_reason"]) == ("out_of_date", "no_longer_true")


def test_advice_expires(recs, admin_engine, clock):
    figures(admin_engine, recs.search, *NO_RESULTS)
    item = open_items(refresh(recs))[0]
    wait(recs, clock, 73)
    assert recs.get(f"{recs.recs}/{item['id']}").json()["data"]["status"] == "expired"
    assert recs.post(f"{recs.recs}/{item['id']}/approve").json()["error"]["code"] == (
        "RECOMMENDATION_CLOSED"
    )


def test_rejected_advice_stays_away_unless_the_loss_doubles(recs, admin_engine):
    figures(admin_engine, recs.search, *NO_RESULTS)
    item = open_items(refresh(recs))[0]
    bad = recs.post(f"{recs.recs}/{item['id']}/reject", {"reason": "maybe"})
    assert bad.status_code == 422
    done = recs.post(
        f"{recs.recs}/{item['id']}/reject", {"reason": "wrong_time", "note": "  Sale next week "}
    ).json()["data"]
    assert (done["status"], done["decision_reason"], done["decision_note"]) == (
        "rejected",
        "wrong_time",
        "Sale next week",
    )
    assert open_items(refresh(recs)) == []
    figures(admin_engine, recs.search, (40, 0, 0), (10, 1, 30))  # AUD 280: the loss doubled
    assert [i["kind"] for i in open_items(refresh(recs))] == ["spend_without_results"]
    assert recs.post(f"{recs.recs}/refresh").json()["error"]["code"] == "REFRESH_LIMIT"


def test_information_is_marked_as_looked_into(recs, admin_engine):
    figures(admin_engine, recs.search, (26, 2, 100), (10, 1, 30))  # cost/conv 91 vs 10
    item = open_items(refresh(recs), "cost_jump")[0]
    assert item["proposal"]["action_type"] is None and item["ready"] is False
    assert recs.post(f"{recs.recs}/{item['id']}/approve").status_code == 409
    done = recs.post(f"{recs.recs}/{item['id']}/done").json()["data"]
    assert done["status"] == "done"
    assert recs.post(f"{recs.recs}/{item['id']}/done").status_code == 409


# ------------------------------------------------------------------ budgets
def test_a_profitable_campaign_held_back_gets_a_bigger_budget(
    recs,
    gsim,  # noqa: F811
    admin_engine,
    monkeypatch,
):
    monkeypatch.setattr(look, "_margin", lambda *a: Margin(Decimal("0.4"), Decimal(1), None))
    figures(admin_engine, recs.search, (50, 5, 200), (40, 4, 160))  # all of AUD 50 a day
    item = open_items(refresh(recs), "budget_limited")[0]
    assert item["proposal"]["params"] == {"daily_budget": "60.00"}
    assert item["proposal"]["text"] == "Raise the daily budget from AUD 50.00 to AUD 60.00"
    done = recs.post(f"{recs.recs}/{item['id']}/approve").json()["data"]
    assert done["action"]["status"] == "succeeded"
    budget = gsim.customers[AU].budgets[0]["campaignBudget"]
    assert budget["amountMicros"] == "60000000"


def test_a_money_losing_campaign_gets_a_smaller_budget(recs, admin_engine, monkeypatch):
    monkeypatch.setattr(look, "_margin", lambda *a: Margin(Decimal("0.4"), Decimal(1), None))
    figures(admin_engine, recs.search, (20, 2, 40), (20, 2, 40))
    item = open_items(refresh(recs), "losing_money")[0]
    assert item["proposal"]["params"] == {"daily_budget": "40.00"}
    assert item["figures"]["break_even"] == "2.50"
    assert "break even" in item["explanation"]


def test_shared_budgets_get_a_closer_look_only(recs, admin_engine, monkeypatch):
    monkeypatch.setattr(look, "_margin", lambda *a: Margin(Decimal("0.4"), Decimal(1), None))
    _exec(admin_engine, "UPDATE ad_budgets SET shared = true")
    figures(admin_engine, recs.search, (20, 2, 40), (20, 2, 40))
    item = open_items(refresh(recs), "losing_money")[0]
    assert item["proposal"]["action_type"] is None and item["note"] == "budget_shared"
    assert item["explanation"].endswith("its budget is shared with other campaigns.")


# ------------------------------------------------------------------ outcomes and schedule
def test_outcomes_are_recorded_after_7_days(recs, admin_engine, clock, runtime):
    figures(admin_engine, recs.search, *NO_RESULTS)
    item = open_items(refresh(recs))[0]
    done = recs.post(f"{recs.recs}/{item['id']}/approve").json()["data"]
    assert done["action"]["status"] == "succeeded"
    wait(recs, clock, 8 * 24)
    look.run_look(runtime, uuid.UUID(recs.org))
    shown = recs.get(f"{recs.recs}/{item['id']}").json()["data"]
    (outcome,) = shown["outcomes"]
    assert outcome["after_days"] == 7
    assert outcome["before"]["figures"]["spend"]["value"] is not None


def test_the_scheduler_starts_one_look_a_day(recs, admin_engine, clock, runtime):
    figures(admin_engine, recs.search, *NO_RESULTS)
    clock.advance(timedelta(hours=-10))  # 01:00 in Sydney: too early
    assert look.enqueue_looks(runtime) == 0
    clock.advance(timedelta(hours=10))  # 11:00 in Sydney
    assert look.enqueue_looks(runtime) == 1
    assert len(open_items(recs.get(recs.recs).json()["data"])) == 1
    assert look.enqueue_looks(runtime) == 0  # once a day
    runtime.settings = runtime.settings.model_copy(update={"OPTIMIZATION_ENABLED": False})
    wait(recs, clock, 24)
    assert look.enqueue_looks(runtime) == 0
    assert recs.post(f"{recs.recs}/refresh").json()["error"]["code"] == "OPTIMIZATION_DISABLED"


# ------------------------------------------------------------------ settings
def test_settings(recs, make_client, admin_engine):
    shown = recs.get(recs.opt).json()["data"]
    assert shown["min_spend"] == "50.00" and shown["budget_step_percent"] == 20
    body = {
        "min_spend": "200",
        "min_conversions": 3,
        "budget_step_percent": 10,
        "cost_jump_percent": 50,
    }
    saved = recs.put(recs.opt, body).json()["data"]
    assert saved["min_spend"] == "200.00" and saved["budget_step_percent"] == 10
    figures(admin_engine, recs.search, *NO_RESULTS)
    assert open_items(refresh(recs)) == []  # AUD 140 is below the new AUD 200
    assert recs.put(recs.opt, {**body, "budget_step_percent": 60}).status_code == 422
    manager = member(make_client, recs, "manager")
    assert manager.get(recs.opt).status_code == 200
    assert manager.put(recs.opt, body).status_code == 403
