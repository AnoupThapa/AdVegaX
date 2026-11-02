"""Explaining and ranking the advice (Phase 11, task 11-04, PHASE_11_PLAN Q-11-4; D16, A12).

**AdVegaX decides; the AI explains.** The model receives only the advice AdVegaX found — each
under a short id (``c1``, ``c2``, …), with its figures already written out, the proposed change
and the periods — never a campaign name, a person or a token. It answers, for every id:
an explanation, a confidence, assumptions, risks and a rank. AdVegaX refuses the answer
(``validate``) if an id is missing, unknown or repeated, a rank is not 1…n, a text is too long,
or a text contains a **number that is not among that item's figures** (an invented figure).
The model cannot add advice, change a value or choose another change: those are not in its
answer at all.

Without the AI (switched off, no key, the daily limit, an answer refused twice) every item gets
AdVegaX's own plain explanation (``rules_text``), marked "Rules only".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.settings import Settings
from app.domains.ai.prompts import Prompt, register
from app.domains.ai.runs import Task
from app.domains.finance.definitions import for_display
from app.domains.funnel.registry import STAGES
from app.domains.optimization.candidates import BUDGET, PAUSE, Candidate

CONFIDENCES = ("low", "medium", "high")
MAX_EXPLANATION = 600
MAX_ITEM = 200
MAX_ITEMS = 3
_STAGE = {s.key: s.label for s in STAGES}
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

NOTES = {
    "budget_on_ad_sets": "the budget is set on its ad sets, not on the campaign",
    "budget_not_daily": "the campaign has no daily budget AdVegaX can change",
    "budget_shared": "its budget is shared with other campaigns",
    "at_maximum": "its budget is already at your maximum daily budget",
    "at_minimum": "its budget is already at the platform's minimum",
    "no_change": "the change would be too small",
}


@dataclass(frozen=True)
class Item:
    """One piece of advice as shown to the model and the person."""

    id: str
    candidate: Candidate
    figures: dict[str, str]  # written out, e.g. {"spend": "AUD 120.50"}
    change: str  # e.g. "Lower the daily budget from AUD 50.00 to AUD 40.00"


def _num(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def money(value: Decimal | None, currency: str) -> str | None:
    if value is None:
        return None
    return f"{currency} {for_display(value, currency):,}"


def _ratio(value: Decimal | None) -> str | None:
    return None if value is None else f"{value.quantize(Decimal('0.01'))}"


def _percent(value: Decimal | None, places: str = "1") -> str | None:
    return None if value is None else f"{(value * 100).quantize(Decimal(places))}%"


def _count(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value.quantize(Decimal('0.01')).normalize():f}"


def written(candidate: Candidate, currency: str) -> dict[str, str]:
    """The figures behind one piece of advice, written out (only those available)."""
    f = candidate.signal.figures
    out: dict[str, str | None]
    if candidate.signal.kind == "funnel_drop":
        out = {
            "rate": _percent(_num(f.get("rate")), "0.01"),
            "previous_rate": _percent(_num(f.get("previous_rate")), "0.01"),
            "baseline_rate": _percent(_num(f.get("baseline_rate")), "0.01"),
            "fall": _percent(-Decimal(f["change"]) if f.get("change") else None, "1"),
        }
    else:
        out = {
            "spend": money(_num(f.get("recent.spend")), currency),
            "conversions": _count(_num(f.get("recent.conversions"))),
            "conversion_value": money(_num(f.get("recent.conversion_value")), currency),
            "value_per_spend": _ratio(_num(f.get("recent.platform_roas"))),
            "cost_per_conversion": money(_num(f.get("recent.cost_per_conversion")), currency),
            "budget_use": _percent(_num(f.get("recent.budget_use")), "1"),
            "baseline_conversions": _count(_num(f.get("baseline.conversions"))),
            "baseline_cost_per_conversion": money(
                _num(f.get("baseline.cost_per_conversion")), currency
            ),
            "gross_margin": _percent(_num(f.get("gross_margin"))),
            "break_even": _ratio(_num(f.get("break_even_roas"))),
            "cost_increase": f"{Decimal(candidate.signal.facts['increase']):.0f}%"
            if candidate.signal.facts.get("increase")
            else None,
        }
    return {k: v for k, v in out.items() if v is not None}


def change_text(candidate: Candidate) -> str:
    p = candidate.proposal
    if p.get("action_type") == PAUSE:
        return "Pause the campaign"
    if p.get("action_type") == BUDGET:
        cur = p["currency"]
        old = money(_num(p.get("previous", {}).get("daily_budget")), cur)
        new = money(Decimal(p["params"]["daily_budget"]), cur)
        verb = "Raise" if candidate.signal.kind == "budget_limited" else "Lower"
        return f"{verb} the daily budget from {old} to {new}"
    return "No change: look into it"


def item_of(index: int, candidate: Candidate, currency: str) -> Item:
    return Item(f"c{index + 1}", candidate, written(candidate, currency), change_text(candidate))


# ------------------------------------------------------------------ AdVegaX's own words
def rules_text(item: Item, settings: Settings, step: int) -> dict[str, Any]:
    """Explanation, confidence, assumptions and risks without the AI."""
    f, kind = item.figures, item.candidate.signal.kind
    days, base = settings.OPTIMIZATION_RECENT_DAYS, settings.OPTIMIZATION_BASELINE_DAYS
    tracking = "The platform's conversion tracking works for this campaign."
    attribution = "The platform counts conversions with its own attribution, not your store's."
    if kind == "spend_without_results":
        text = (
            f"In the last {days} days this campaign spent {f.get('spend')} and the platform "
            "recorded no conversions. Pausing it stops the spend until you have checked its "
            "ads, keywords and landing page."
        )
        assumptions = [tracking]
        risks = [
            "Conversions the platform reports late are not counted yet.",
            "Pausing stops all traffic from this campaign.",
        ]
        confidence = "medium"
    elif kind == "losing_money":
        text = (
            f"In the last {days} days this campaign brought {f.get('conversion_value')} of "
            f"conversion value for {f.get('spend')} spent: {f.get('value_per_spend')} for every "
            f"1 spent. With your gross margin of {f.get('gross_margin')} it needs at least "
            f"{f.get('break_even')} to break even. A {step}% lower budget limits the loss."
        )
        assumptions = [tracking, "Your business's gross margin applies to this campaign."]
        risks = [attribution, "A lower budget can also mean fewer sales."]
        confidence = "medium"
    elif kind == "budget_limited":
        text = (
            f"In the last {days} days this campaign used {f.get('budget_use')} of its daily "
            f"budget and brought {f.get('value_per_spend')} of conversion value for every 1 "
            f"spent, above the break-even level of {f.get('break_even')}. A {step}% higher "
            "budget lets it reach more buyers."
        )
        assumptions = [tracking, "Results stay similar with more budget."]
        risks = [attribution, "Extra spend usually brings results at a higher cost."]
        confidence = "medium"
    elif kind == "cost_jump":
        text = (
            f"Its cost per conversion was {f.get('cost_per_conversion')} in the last {days} "
            f"days, {f.get('cost_increase')} higher than {f.get('baseline_cost_per_conversion')} "
            f"in the {base} days before. Look into what changed: competition, bids, ads or the "
            "landing page."
        )
        assumptions = [tracking]
        risks = ["A short-term change can settle by itself."]
        confidence = "low"
    else:
        facts = item.candidate.signal.facts
        step_text = (
            f"{_STAGE.get(facts['to_stage'], facts['to_stage'])} per "
            f"{_STAGE.get(facts['from_stage'], facts['from_stage'])}"
        )
        where = "your business" if facts["view"] == "whole" else "this ad platform's own funnel"
        text = (
            f"In {where}, {step_text} fell to {f.get('rate')} from {f.get('previous_rate')} in "
            f"the previous period, below its usual {f.get('baseline_rate')}. Look into the "
            "pages and steps between these two stages."
        )
        assumptions = ["The stages are counted the same way in both periods."]
        risks = ["A change in tracking can look like a drop."]
        confidence = "low"
    note = item.candidate.note
    if note in NOTES:
        text += f" No budget change is proposed: {NOTES[note]}."
    return {
        "explanation": text,
        "confidence": confidence,
        "assumptions": assumptions,
        "risks": risks,
    }


# ------------------------------------------------------------------ the AI
SYSTEM = f"""You are AdVegaX's optimization analyst. AdVegaX has already found, with fixed \
rules, a few things worth a merchant's attention in their advertising, and the change it \
proposes for each (or none). You explain each one to the merchant and rank them. You never \
decide or make changes; the merchant approves or rejects each piece of advice.

Rules:
1. Answer for every item, by its id, exactly once. Rank them 1, 2, 3, … from the most to the \
least important for the merchant's profit.
2. Use only the figures given for that item, written exactly as given. Never invent or \
calculate other figures, and never change the proposed change.
3. "explanation": what was noticed and why the proposed change (or a closer look) makes sense, \
at most {MAX_EXPLANATION} characters, plain English, no jargon.
4. "confidence": low, medium or high — how strongly the figures support the advice.
5. "assumptions" and "risks": at most {MAX_ITEMS} each, at most {MAX_ITEM} characters each.
6. Conversions and conversion value are the ad platform's own figures, with its attribution."""

TEMPLATE = """Explain and rank this advice.

Periods: the last {recent_days} full days, compared with the {baseline_days} days before.
Reporting currency: {currency}

The advice (JSON):
{items}"""

OPTIMIZER = register(Prompt("optimization", "v1", SYSTEM, TEMPLATE))


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_LIST = {"type": "array", "items": {"type": "string"}}
ANSWER_SCHEMA: dict[str, Any] = _object(
    {
        "items": {
            "type": "array",
            "minItems": 1,
            "items": _object(
                {
                    "id": {"type": "string"},
                    "rank": {"type": "integer"},
                    "explanation": {"type": "string"},
                    "confidence": {"type": "string", "enum": list(CONFIDENCES)},
                    "assumptions": _LIST,
                    "risks": _LIST,
                }
            ),
        }
    }
)


def _normal(token: str) -> str:
    return format(Decimal(token.replace(",", "")).normalize(), "f")


def numbers_in(text: str) -> set[str]:
    return {_normal(t) for t in _NUMBER.findall(text)}


def allowed_numbers(item: Item, extra: tuple[int, ...]) -> set[str]:
    found: set[str] = {str(n) for n in (1, 100, *extra)}
    for text in (*item.figures.values(), item.change):
        found |= numbers_in(text)
    return found


def validate(answer: Any, items: list[Item], extra: tuple[int, ...]) -> list[str]:
    if not isinstance(answer, dict) or not isinstance(answer.get("items"), list):
        return ["shape:answer"]
    by_id = {i.id: i for i in items}
    seen: list[str] = []
    reasons: list[str] = []
    for entry in answer["items"]:
        if not isinstance(entry, dict) or entry.get("id") not in by_id:
            reasons.append("unknown_item")
            continue
        key = str(entry["id"])
        if key in seen:
            reasons.append(f"repeated_item:{key}")
            continue
        seen.append(key)
        texts = [
            entry.get("explanation"),
            *(entry.get("assumptions") or []),
            *(entry.get("risks") or []),
        ]
        if not all(isinstance(t, str) and t.strip() for t in texts):
            reasons.append(f"{key}.text_invalid")
            continue
        if len(entry["explanation"]) > MAX_EXPLANATION:
            reasons.append(f"{key}.explanation_too_long")
        for field in ("assumptions", "risks"):
            values = entry.get(field) or []
            if len(values) > MAX_ITEMS or any(len(v) > MAX_ITEM for v in values):
                reasons.append(f"{key}.{field}_invalid")
        if entry.get("confidence") not in CONFIDENCES:
            reasons.append(f"{key}.confidence_invalid")
        invented = set().union(*(numbers_in(str(t)) for t in texts)) - allowed_numbers(
            by_id[key], extra
        )
        if invented:
            reasons.append(f"{key}.figure_not_given")
    missing = [i for i in by_id if i not in seen]
    if missing:
        reasons.append("missing_items:" + ",".join(missing))
    if not reasons:
        ranks = sorted(int(e.get("rank") or 0) for e in answer["items"])
        if ranks != list(range(1, len(items) + 1)):
            reasons.append("ranks_invalid")
    return reasons


def optimizer_task(items: list[Item], settings: Settings, currency: str, step: int) -> Task:
    extra = (settings.OPTIMIZATION_RECENT_DAYS, settings.OPTIMIZATION_BASELINE_DAYS, step)
    shown = [
        {
            "id": i.id,
            "kind": i.candidate.signal.kind,
            "platform": i.candidate.signal.facts.get("platform") or None,
            "figures": i.figures,
            "proposed_change": i.change,
        }
        for i in items
    ]
    text = json.dumps(shown, indent=1, sort_keys=True)
    return Task(
        name="optimization",
        prompt=OPTIMIZER,
        parts={
            "recent_days": str(settings.OPTIMIZATION_RECENT_DAYS),
            "baseline_days": str(settings.OPTIMIZATION_BASELINE_DAYS),
            "currency": currency,
            "items": text,
        },
        schema=ANSWER_SCHEMA,
        snapshot={"currency": currency, "items": shown},
        validate=lambda answer: validate(answer, items, extra),
    )
