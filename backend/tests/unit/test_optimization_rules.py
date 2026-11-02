"""The optimization engine's fixed rules, proposals and AI checks (Phase 11, 11-02 … 11-04)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal

import pytest
from app.core.settings import Settings
from app.domains.funnel.findings import Finding
from app.domains.metrics.engine import Figure, missing
from app.domains.optimization.candidates import Candidate, budget_problem, new_budget
from app.domains.optimization.explain import (
    item_of,
    numbers_in,
    optimizer_task,
    rules_text,
    validate,
)
from app.domains.optimization.signals import (
    CampaignInput,
    Margin,
    Thresholds,
    evaluate,
    funnel_signals,
    margin_of,
)

D = Decimal
T = Thresholds(
    min_spend=D(50),
    min_conversions=5,
    budget_step_percent=20,
    cost_jump_percent=30,
    budget_use=D("0.95"),
    winner_factor=D("1.2"),
    margin_coverage=D("0.8"),
)
MARGIN = Margin(D("0.4"), D("0.9"), None)  # break even at 2.5
SETTINGS = Settings()


def fig(value) -> Figure:
    return Figure(D(str(value)))


def campaign(status="active", **recent) -> CampaignInput:
    figures = {
        "spend": fig(100),
        "clicks": fig(200),
        "conversions": fig(10),
        "conversion_value": fig(300),
        "platform_roas": fig(3),
        "cost_per_conversion": fig(10),
        "budget_use": fig("0.5"),
    }
    figures.update({k: v if isinstance(v, Figure) else fig(v) for k, v in recent.items()})
    return CampaignInput(
        id=uuid.UUID(int=1),
        ad_account_id=uuid.UUID(int=2),
        provider="google_ads",
        name="Gloves - Search",
        status=status,
        recent=figures,
        baseline={"conversions": fig(40), "cost_per_conversion": fig(10), "spend": fig(400)},
    )


def kinds(c, margin=MARGIN, t=T):
    return [s.kind for s in evaluate(c, margin, t)]


def test_a_healthy_campaign_gets_no_advice():
    assert kinds(campaign()) == []


def test_spend_without_results():
    found = evaluate(campaign(conversions=0, conversion_value=0, platform_roas=0), MARGIN, T)
    assert [s.kind for s in found] == ["spend_without_results"]
    assert found[0].facts["loss"] == "100"
    assert found[0].fingerprint == f"spend_without_results:{uuid.UUID(int=1)}"


@pytest.mark.parametrize(
    "changes",
    [
        {"spend": 49},  # below the minimum
        {"spend": missing("not_synced", "not_synced")},  # never treated as 0
        {"conversions": missing("unavailable", "not_provided")},
    ],
)
def test_never_on_small_or_missing_figures(changes):
    assert kinds(campaign(**{"conversions": 0, **changes})) == []


def test_paused_campaigns_are_left_alone():
    assert kinds(campaign(status="paused", conversions=0)) == []


def test_losing_money_against_the_break_even_level():
    found = evaluate(campaign(platform_roas=2, conversion_value=200), MARGIN, T)
    assert [s.kind for s in found] == ["losing_money"]
    assert found[0].facts["loss"] == "20"  # 100 spent - 200 x 40 %
    assert found[0].figures["break_even_roas"] == "2.5"


def test_profit_rules_need_a_known_margin_and_history():
    unknown = Margin(None, D("0.5"), "costs_missing")
    assert kinds(campaign(platform_roas=2), margin=unknown) == []
    c = campaign(platform_roas=2)
    few = replace(c, baseline={**c.baseline, "conversions": fig(4)})
    assert kinds(few) == []


def test_held_back_by_budget():
    assert kinds(campaign(budget_use="0.96", platform_roas=3)) == ["budget_limited"]
    assert kinds(campaign(budget_use="0.96", platform_roas="2.9")) == []  # not 1.2 x 2.5
    assert kinds(campaign(budget_use=missing("unsupported", "shared_budget"))) == []


def test_cost_per_conversion_jump():
    found = evaluate(campaign(cost_per_conversion=13), MARGIN, T)
    assert [s.kind for s in found] == ["cost_jump"]
    assert found[0].facts["increase"] == "30"
    assert kinds(campaign(cost_per_conversion="12.9")) == []


def test_margin_of_products():
    sales = [(fig(100), fig(40)), (fig(50), missing("unavailable", "missing_product_costs"))]
    assert margin_of(sales, D("0.6")) == Margin(D("0.4"), D(100) / D(150), None)
    assert margin_of(sales, D("0.8")).reason == "costs_missing"
    assert margin_of([], D("0.8")).reason == "no_sales"
    assert margin_of([(fig(100), fig(-5))], D("0.8")).reason == "no_margin"
    assert Margin(D("0.4"), D(1), None).break_even == D("2.5")
    assert Margin(None, None, "no_sales").break_even is None


def test_funnel_findings_become_information():
    finding = Finding(
        view="platform",
        subject="meta_ads",
        from_stage="clicks",
        to_stage="purchases",
        rate=D("0.01"),
        previous_rate=D("0.02"),
        baseline_rate=D("0.018"),
        events_before=D(1000),
        change=D("-0.5"),
    )
    channel = replace(finding, view="channel", subject="Paid Search")
    found = funnel_signals([finding, channel])
    assert [s.fingerprint for s in found] == ["funnel_drop:platform:meta_ads:clicks:purchases"]
    assert found[0].campaign_id is None and found[0].facts["platform"] == "meta_ads"


# ------------------------------------------------------------------ proposals
def test_new_budget_steps_and_bounds():
    assert new_budget(D(50), 20, True, "AUD", D("1.6"), D(500)) == (D("60.00"), None)
    assert new_budget(D(50), 20, False, "AUD", D("1.6"), D(500)) == (D("40.00"), None)
    assert new_budget(D(450), 20, True, "AUD", None, D(500)) == (D("500.00"), None)
    assert new_budget(D(500), 20, True, "AUD", None, D(500)) == (None, "at_maximum")
    assert new_budget(D(2), 20, False, "AUD", D("1.80"), None) == (D("1.80"), None)
    assert new_budget(D("1.80"), 20, False, "AUD", D("1.80"), None) == (None, "at_minimum")
    assert new_budget(D(1000), 20, True, "JPY", None, None) == (D(1200), None)


D50 = D(50)


class _Budget:
    def __init__(self, level="campaign", period="daily", amount=D50, shared=False):
        self.level, self.period, self.amount, self.shared = level, period, amount, shared


def test_only_a_campaign_s_own_daily_budget_is_changed():
    assert budget_problem(None) == "budget_on_ad_sets"
    assert budget_problem(_Budget(level="ad_group")) == "budget_on_ad_sets"
    assert budget_problem(_Budget(period="lifetime")) == "budget_not_daily"
    assert budget_problem(_Budget(amount=None)) == "budget_not_daily"
    assert budget_problem(_Budget(shared=True)) == "budget_shared"
    assert budget_problem(_Budget()) is None


# ------------------------------------------------------------------ explaining
def _candidate(kind="losing_money", proposal=None, note=None):
    c = campaign(platform_roas=2, conversion_value=200)
    signal = evaluate(c, MARGIN, T)[0]
    signal = replace(signal, kind=kind, facts={**signal.facts, "increase": "30"})
    return Candidate(
        signal,
        proposal
        if proposal is not None
        else {
            "action_type": "campaign.set_daily_budget",
            "params": {"daily_budget": "40.00"},
            "currency": "AUD",
            "previous": {"daily_budget": "50.00"},
        },
        [],
        {"status": "active"},
        note,
    )


def test_figures_are_written_out_and_the_change_described():
    item = item_of(0, _candidate(), "AUD")
    assert item.id == "c1"
    assert item.figures["spend"] == "AUD 100.00"
    assert item.figures["gross_margin"] == "40%"
    assert item.figures["break_even"] == "2.50"
    assert item.change == "Lower the daily budget from AUD 50.00 to AUD 40.00"
    pause = item_of(
        1, _candidate("spend_without_results", {"action_type": "campaign.pause"}), "AUD"
    )
    assert pause.change == "Pause the campaign"
    look = item_of(2, _candidate("cost_jump", {}), "AUD")
    assert look.change == "No change: look into it"


@pytest.mark.parametrize(
    "kind", ["spend_without_results", "losing_money", "budget_limited", "cost_jump"]
)
def test_rules_only_texts(kind):
    text = rules_text(item_of(0, _candidate(kind, {}, "budget_shared"), "AUD"), SETTINGS, 20)
    assert text["confidence"] in ("low", "medium", "high")
    assert text["assumptions"] and text["risks"]
    assert "None" not in text["explanation"]
    assert text["explanation"].endswith("its budget is shared with other campaigns.")


def test_rules_text_for_a_funnel_drop():
    signal = funnel_signals(
        [
            Finding(
                view="whole",
                subject=None,
                from_stage="sessions",
                to_stage="orders",
                rate=D("0.01"),
                previous_rate=D("0.02"),
                baseline_rate=D("0.018"),
                events_before=D(1000),
                change=D("-0.5"),
            )
        ]
    )[0]
    item = item_of(0, Candidate(signal, {}, [], {}, None), "AUD")
    assert item.figures == {
        "rate": "1.00%",
        "previous_rate": "2.00%",
        "baseline_rate": "1.80%",
        "fall": "50%",
    }
    assert "your business" in rules_text(item, SETTINGS, 20)["explanation"]


def _answer(**changes):
    entry = {
        "id": "c1",
        "rank": 1,
        "explanation": "It brought 2.00 for every 1 spent, below 2.5 needed with a 40% margin.",
        "confidence": "medium",
        "assumptions": ["The tracking works."],
        "risks": ["Fewer sales."],
    }
    entry.update(changes)
    return {"items": [entry]}


def test_the_ai_answer_is_checked():
    items = [item_of(0, _candidate(), "AUD")]
    extra = (7, 28, 20)
    assert validate(_answer(), items, extra) == []
    assert validate({"nope": 1}, items, extra) == ["shape:answer"]
    assert validate(_answer(id="c9"), items, extra) == ["unknown_item", "missing_items:c1"]
    assert validate(_answer(rank=2), items, extra) == ["ranks_invalid"]
    assert validate(_answer(explanation="x" * 601), items, extra) == ["c1.explanation_too_long"]
    assert validate(_answer(risks=["a"] * 4), items, extra) == ["c1.risks_invalid"]
    assert validate(_answer(confidence="sure"), items, extra) == ["c1.confidence_invalid"]
    assert validate(_answer(explanation=" "), items, extra) == ["c1.text_invalid"]
    invented = _answer(explanation="It will bring AUD 1,000 next week.")
    assert validate(invented, items, extra) == ["c1.figure_not_given"]
    twice = {"items": _answer()["items"] * 2}
    assert validate(twice, items, extra) == ["repeated_item:c1"]


def test_numbers_are_compared_as_numbers():
    assert numbers_in("AUD 1,200.50 and 2.50, 40.0% in 7 days") == {"1200.5", "2.5", "40", "7"}


def test_the_task_sends_no_campaign_name():
    item = item_of(0, _candidate(), "AUD")
    task = optimizer_task([item], SETTINGS, "AUD", 20)
    assert "Gloves" not in task.parts["items"]
    assert task.snapshot["items"][0]["id"] == "c1"
    assert task.validate(_answer()) == []
