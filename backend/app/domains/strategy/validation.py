"""The validation chain every strategy passes (Phase 8, task 8-04, PLAN Q-8-6; A12, D16).

Run on every model answer **and on every edit** (8-05), in this order; a stage only runs when
the earlier ones found nothing, so reasons are about one problem at a time:

1. **Shape** — exactly the schema's fields and types (``schema.py``), allowed values, lengths
   and counts, a campaign type that exists on its platform, one entry per platform and target,
   shares as percentages with at most two decimals, target ranges with ``0 <= low <= high``.
2. **Existence** — exactly the platforms the merchant asked for, each connected; the objective
   asked for; every evidence key one of the context's figures, and one AdVegaX actually has
   (a recommendation cannot rest on an unknown figure).
3. **Business rules** — an unknown or negative margin, stock below recent sales and a short
   history must each be named as a risk; targets must overlap the organization's own history
   (within ``PLANNER_TARGET_FACTOR`` times either way) where AdVegaX has it.
4. **Budget** — shares add up to 100 %; the computed amounts respect each platform's minimum.

Reasons are plain keys (``code`` or ``code:detail``), never the model's text: they are recorded,
sent back to the model once (``runs.py``) and shown to the merchant.

``plannable`` is checked **before** the model is asked: an inactive or out-of-stock product, or
no connected ad platform, is never planned (``PRODUCT_NOT_PLANNABLE``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domains.strategy import budget as budgets
from app.domains.strategy.context import PlanningContext
from app.domains.strategy.schema import (
    ANSWER_SCHEMA,
    CAMPAIGN_TYPES,
    MAX_ANGLES,
    MAX_ASSUMPTIONS,
    MAX_EVIDENCE,
    MAX_RISKS,
    MAX_SHORT,
    MAX_SUMMARY,
    MAX_TARGETS,
    MAX_TEXT,
    SHARE_PLACES,
)

LIMITED_HISTORY_DAYS = 30
_LENGTHS = {"summary": MAX_SUMMARY, "angle": MAX_SHORT, "text": MAX_SHORT}
_COUNTS = {
    "angles": MAX_ANGLES,
    "targets": MAX_TARGETS,
    "risks": MAX_RISKS,
    "assumptions": MAX_ASSUMPTIONS,
    "evidence": MAX_EVIDENCE,
}


@dataclass(frozen=True)
class StrategyRequest:
    product_id: Any
    platforms: tuple[str, ...]
    objective: str | None
    budget: budgets.Budget


# ------------------------------------------------------------------ 0. before the model
def plannable(context: PlanningContext) -> list[str]:
    reasons = []
    if context.facts["product_status"] != "active":
        reasons.append("product_not_active")
    stock = context.figures["product.stock_available"]
    if context.facts["stock_tracked"] and stock.value is not None and stock.value <= 0:
        reasons.append("out_of_stock")
    if not context.platforms:
        reasons.append("no_ad_platform")
    return reasons


# ------------------------------------------------------------------ 1. shape
def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _shape(value: Any, schema: dict[str, Any], path: str, reasons: list[str]) -> None:
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict) or set(value) != set(schema["properties"]):
            reasons.append(f"shape:{path or 'answer'}")
            return
        for key, sub in schema["properties"].items():
            _shape(value[key], sub, f"{path}.{key}" if path else key, reasons)
    elif kind == "array":
        if not isinstance(value, list):
            reasons.append(f"shape:{path}")
            return
        name = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if len(value) < schema.get("minItems", 0):
            reasons.append(f"empty:{path}")
        if len(value) > _COUNTS.get(name, len(value)):
            reasons.append(f"too_many:{path}")
        for i, item in enumerate(value):
            _shape(item, schema["items"], f"{path}[{i}]", reasons)
    elif kind == "string":
        if not isinstance(value, str):
            reasons.append(f"shape:{path}")
            return
        if "enum" in schema and value not in schema["enum"]:
            reasons.append(f"unknown_value:{path}")
            return
        name = path.rsplit(".", 1)[-1].split("[", 1)[0]
        limit = _LENGTHS.get(name, MAX_TEXT)
        if "enum" not in schema and not value.strip():
            reasons.append(f"empty:{path}")
        elif len(value) > limit:
            reasons.append(f"too_long:{path}")
    elif kind == "number" and _number(value) is None:
        reasons.append(f"shape:{path}")


def shape_reasons(answer: Any) -> list[str]:
    reasons: list[str] = []
    _shape(answer, ANSWER_SCHEMA, "", reasons)
    if reasons:
        return reasons
    seen: set[str] = set()
    for entry in answer["platforms"]:
        platform, share = entry["platform"], _number(entry["budget_share_percent"])
        if platform in seen:
            reasons.append(f"duplicate_platform:{platform}")
        seen.add(platform)
        if entry["campaign_type"] not in CAMPAIGN_TYPES[platform]:
            reasons.append(f"campaign_type_not_for_platform:{platform}")
        if share is None or share.as_tuple().exponent < -SHARE_PLACES:  # type: ignore[operator]
            reasons.append(f"share_invalid:{platform}")
    metrics: set[str] = set()
    for target in answer["targets"]:
        metric = target["metric"]
        if metric in metrics:
            reasons.append(f"duplicate_target:{metric}")
        metrics.add(metric)
        low, high = _number(target["low"]), _number(target["high"])
        if low is None or high is None or not Decimal(0) <= low <= high:
            reasons.append(f"target_range_invalid:{metric}")
    return reasons


# ------------------------------------------------------------------ 2. existence
def _evidence_keys(answer: dict[str, Any]) -> list[str]:
    keys = [k for p in answer["platforms"] for k in p["evidence"]]
    keys += [k for a in answer["angles"] for k in a["evidence"]]
    keys += [k for t in answer["targets"] for k in t["evidence"]]
    return list(dict.fromkeys(keys))


def existence_reasons(
    answer: dict[str, Any], context: PlanningContext, request: StrategyRequest
) -> list[str]:
    reasons = []
    named = [p["platform"] for p in answer["platforms"]]
    for platform in named:
        if platform not in request.platforms:
            reasons.append(f"platform_not_requested:{platform}")
        elif platform not in context.platforms:
            reasons.append(f"platform_not_connected:{platform}")
    reasons += [f"platform_missing:{p}" for p in request.platforms if p not in named]
    if request.objective is not None and answer["objective"] != request.objective:
        reasons.append("objective_not_requested")
    for key in _evidence_keys(answer):
        figure = context.figures.get(key)
        if figure is None:
            reasons.append(f"unknown_evidence:{key[:80]}")
        elif figure.value is None:
            reasons.append(f"evidence_not_available:{key}")
    return reasons


# ------------------------------------------------------------------ 3. business rules
def _value(context: PlanningContext, key: str) -> Decimal | None:
    figure = context.figures.get(key)
    return None if figure is None else figure.value


def margin(context: PlanningContext) -> Decimal | None:
    """The product's margin: from its sales, else from today's price and unit cost (the
    highest cost against the lowest price, the cautious view); None when neither is known."""
    sold = _value(context, "product.gross_margin")
    if sold is not None:
        return sold
    price, cost = _value(context, "product.price_min"), _value(context, "product.unit_cost_max")
    if price is None or cost is None or price <= 0:
        return None
    return (price - cost) / price


def required_risks(context: PlanningContext) -> list[str]:
    needed = []
    found = margin(context)
    if found is None:
        needed.append("margin_unknown")
    elif found <= 0:
        needed.append("margin_negative")
    stock, recent = (
        _value(context, "product.stock_available"),
        _value(context, "product.recent_units"),
    )
    if stock is not None and recent is not None and stock < recent:
        needed.append("low_stock")
    if context.facts["period"]["days"] < LIMITED_HISTORY_DAYS:
        needed.append("limited_history")
    return needed


def history(context: PlanningContext, metric: str, platforms: tuple[str, ...]) -> list[Decimal]:
    """The organization's own figures a target is compared with (zero values are left out:
    a ROAS of 0 is no guide to a reasonable target)."""
    if metric == "roas":
        values = [_value(context, "business.blended_roas")]
    elif metric == "cost_per_order":
        spend, orders = _value(context, "business.ad_spend"), _value(context, "business.orders")
        values = [spend / orders if spend is not None and orders else None]
    else:
        values = [_value(context, f"platform.{p}.{metric}") for p in platforms]
    return [v for v in values if v is not None and v > 0]


def business_reasons(
    answer: dict[str, Any], context: PlanningContext, request: StrategyRequest, factor: Decimal
) -> list[str]:
    named = {r["code"] for r in answer["risks"]}
    reasons = [f"risk_missing:{code}" for code in required_risks(context) if code not in named]
    for target in answer["targets"]:
        known = history(context, target["metric"], request.platforms)
        if not known:
            continue
        low, high = Decimal(str(target["low"])), Decimal(str(target["high"]))
        if high < min(known) / factor or low > max(known) * factor:
            reasons.append(f"target_outside_history:{target['metric']}")
    return reasons


# ------------------------------------------------------------------ 4. budget
def shares_of(answer: dict[str, Any]) -> dict[str, Decimal]:
    return {p["platform"]: Decimal(str(p["budget_share_percent"])) for p in answer["platforms"]}


def budget_reasons(
    answer: dict[str, Any], request: StrategyRequest, minimums: dict[str, Decimal | None]
) -> list[str]:
    shares = shares_of(answer)
    reasons = budgets.share_reasons(shares)
    if reasons:
        return reasons
    split = budgets.amounts(request.budget, shares)
    return budgets.minimum_reasons(request.budget, split, minimums)


# ------------------------------------------------------------------ the chain
def validate(
    answer: Any,
    context: PlanningContext,
    request: StrategyRequest,
    *,
    minimums: dict[str, Decimal | None],
    target_factor: Decimal,
) -> list[str]:
    """[] when the strategy may be shown; else the reasons of the first stage that failed."""
    reasons = shape_reasons(answer)
    if not reasons:
        reasons = existence_reasons(answer, context, request)
    if not reasons:
        reasons = business_reasons(answer, context, request, target_factor)
    if not reasons:
        reasons = budget_reasons(answer, request, minimums)
    return list(dict.fromkeys(reasons))
