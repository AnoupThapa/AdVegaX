"""What each finding proposes, with exact values (Phase 11, task 11-03, PHASE_11_PLAN Q-11-2,
Q-11-11; A30).

Only what the Action Engine already does:

* **spend without results** → pause the campaign;
* **losing money** → lower its daily budget by ``budget_step_percent``;
* **held back by budget** → raise it by ``budget_step_percent`` (never above the organization's
  maximum, never below the platform's minimum);
* **cost per conversion jumped**, **funnel drop-off** → "look into it": no change.

A budget is proposed only for a campaign that holds its own daily budget, not shared with other
campaigns (as 10A); otherwise the advice is "look into it", with the reason. The values are then
**pre-checked** with the 10A checks on AdVegaX's own copy of the campaign (the platform is read
again when the change is requested). A campaign with a change already open gets no advice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.actions import validation
from app.domains.actions.catalogue import CATALOGUE
from app.domains.actions.facts import (
    budget_bounds,
    limits_for,
    load_target,
    resource_reason,
    write_access_problem,
    writer_for,
)
from app.domains.actions.models import OPEN_STATUSES, Action
from app.domains.actions.validation import Facts
from app.domains.advertising.models import AdBudget
from app.domains.finance.definitions import minor_units
from app.domains.optimization.signals import HUNDRED, Signal
from app.providers.base.changes import CampaignSnapshot
from app.providers.base.types import AdEntityStatus
from app.runtime import Runtime

PAUSE = "campaign.pause"
BUDGET = "campaign.set_daily_budget"


@dataclass(frozen=True)
class Candidate:
    signal: Signal
    proposal: dict[str, Any]  # {} = look into it
    prechecks: list[dict[str, Any]]
    campaign_state: dict[str, Any]
    note: str | None  # why no change is proposed (e.g. budget_shared), or None


def budget_problem(budget: AdBudget | None) -> str | None:
    if budget is None or budget.level != "campaign":
        return "budget_on_ad_sets"
    if budget.period != "daily" or budget.amount is None:
        return "budget_not_daily"
    if budget.shared:
        return "budget_shared"
    return None


def _round(value: Decimal, currency: str) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-minor_units(currency)), rounding=ROUND_HALF_UP)


def new_budget(
    current: Decimal,
    step: int,
    up: bool,
    currency: str,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> tuple[Decimal | None, str | None]:
    """The proposed daily budget, or why none (at the maximum / minimum already)."""
    factor = (HUNDRED + step) / HUNDRED if up else (HUNDRED - step) / HUNDRED
    value = _round(current * factor, currency)
    if up and maximum is not None and value > maximum:
        value = _round(maximum, currency)
        if value <= current:
            return None, "at_maximum"
    if not up and minimum is not None and value < minimum:
        value = minimum.quantize(Decimal(1).scaleb(-minor_units(currency)), rounding=ROUND_CEILING)
        if value >= current:
            return None, "at_minimum"
    if value == current:
        return None, "no_change"
    return value, None


def has_open_change(session: Session, org_id: uuid.UUID, campaign_id: uuid.UUID) -> bool:
    return (
        session.execute(
            select(Action.id).where(
                Action.organization_id == org_id,
                Action.campaign_id == campaign_id,
                Action.status.in_(OPEN_STATUSES),
            )
        ).first()
        is not None
    )


def state_of(session: Session, budget_id: uuid.UUID | None, status: str) -> dict[str, Any]:
    budget = session.get(AdBudget, budget_id) if budget_id is not None else None
    return {
        "status": status,
        "budget_id": str(budget.id) if budget else None,
        "daily_budget": str(budget.amount)
        if budget is not None and budget.amount is not None
        else None,
        "currency": budget.currency if budget else None,
    }


def candidate_for(
    rt: Runtime, session: Session, org_id: uuid.UUID, signal: Signal, step: int
) -> Candidate | None:
    """The proposal and its pre-checks (None: the campaign has a change open already)."""
    if signal.campaign_id is None:
        return Candidate(signal, {}, [], {}, None)
    if has_open_change(session, org_id, signal.campaign_id):
        return None
    target = load_target(session, org_id, signal.campaign_id)
    campaign, account = target.campaign, target.account
    budget = session.get(AdBudget, campaign.budget_id) if campaign.budget_id else None
    state = state_of(session, campaign.budget_id, campaign.status)
    kind = signal.kind
    if kind == "spend_without_results":
        proposal: dict[str, Any] = {"action_type": PAUSE, "params": {}}
    elif kind in ("losing_money", "budget_limited"):
        problem = budget_problem(budget)
        if problem is not None:
            return Candidate(signal, {}, [], state, problem)
        assert budget is not None
        assert budget.amount is not None
        minimum, maximum, _ = budget_bounds(rt, session, org_id, account.provider, account.currency)
        value, why = new_budget(
            budget.amount, step, kind == "budget_limited", account.currency, minimum, maximum
        )
        if value is None:
            return Candidate(signal, {}, [], state, why)
        proposal = {"action_type": BUDGET, "params": {"daily_budget": str(value)}}
    else:
        return Candidate(signal, {}, [], state, None)

    spec = CATALOGUE[proposal["action_type"]]
    writer = writer_for(rt, account.provider)
    reason = resource_reason(target, writer) or write_access_problem(target.connection, writer)
    known = {s.value for s in AdEntityStatus}
    snapshot = CampaignSnapshot(
        external_id=campaign.external_campaign_id,
        status=AdEntityStatus(campaign.status) if campaign.status in known else None,
        budget_level=budget.level if budget else None,
        budget_period=budget.period if budget else None,
        daily_budget=budget.amount if budget else None,
        budget_shared=bool(budget.shared) if budget else False,
        budget_external_id=budget.external_budget_id if budget else None,
    )
    checks = validation.run(
        Facts(
            spec=spec,
            params=dict(proposal["params"]),
            params_reason=None,
            resource_reason=reason,
            snapshot=snapshot,
            limits=limits_for(rt, session, target, spec, undo=False),
        )
    )
    proposal["currency"] = account.currency
    if kind != "spend_without_results":
        proposal["previous"] = {"daily_budget": str(budget.amount) if budget else None}
    return Candidate(signal, proposal, [c.as_json() for c in checks], state, None)
