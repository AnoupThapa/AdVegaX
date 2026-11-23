"""The checks every change passes before it can be approved (Phase 10A, 10A-02, Q-10A-4/5).

In order: **shape** (the change and its values) → **resource** (the campaign is the
organization's, its account is linked and allows changes) → **business rules** (the limits)
→ **state** (the campaign, as the platform reports it now, is in a state where the change
makes sense). The platform's own dry run, the person's authority and the duplicate check
follow in the service. Every check is recorded with its result; a later group is skipped when
an earlier one fails, so the reasons shown are always the first ones to fix.

Pure functions: the service gathers the facts (``Facts``), this module decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.domains.actions.catalogue import ActionSpec
from app.providers.base.changes import CampaignSnapshot, ChangeKind
from app.providers.base.types import AdEntityStatus

HUNDRED = Decimal(100)


@dataclass(frozen=True)
class Limits:
    increase_percent: int
    decrease_percent: int
    minimum: Decimal | None  # the platform's minimum daily budget (None: no exchange rate)
    maximum: Decimal | None  # the organization's maximum, in the account currency
    maximum_set: bool  # whether the organization chose a maximum at all
    budget_changed_recently: bool
    volume_used: int
    volume_limit: int
    undo: bool = False  # an undo restores an earlier value: no step or frequency limit


@dataclass(frozen=True)
class Facts:
    spec: ActionSpec
    params: dict[str, str] | None  # None: the values were refused (``params_reason``)
    params_reason: str | None
    resource_reason: str | None
    snapshot: CampaignSnapshot | None
    limits: Limits


@dataclass(frozen=True)
class Check:
    check: str
    result: str  # passed | failed | skipped
    reason: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"check": self.check, "result": self.result, "reason": self.reason}


GROUPS = ("shape", "resource", "budget", "limits", "state")


def _state_reason(spec: ActionSpec, status: AdEntityStatus | None) -> str | None:
    if status in spec.states:
        return None
    if status is None or status in (AdEntityStatus.REMOVED, AdEntityStatus.ARCHIVED):
        return "campaign_not_changeable"
    if spec.kind is ChangeKind.PAUSE:
        return "already_paused"
    if spec.kind is ChangeKind.RESUME:
        return "already_active"
    return "campaign_not_changeable"  # pragma: no cover - budgets apply to active and paused


def _budget_reason(snapshot: CampaignSnapshot, new: Decimal) -> str | None:
    if snapshot.budget_level == "ad_group":
        return "budget_on_ad_sets"
    if snapshot.budget_level != "campaign" or snapshot.budget_period != "daily":
        return "budget_not_daily"
    if snapshot.budget_shared:
        return "budget_shared"
    if snapshot.daily_budget is None:
        return "budget_not_daily"
    if new == snapshot.daily_budget:
        return "no_change"
    return None


def _limit_reasons(limits: Limits, current: Decimal | None, new: Decimal | None) -> list[str]:
    reasons: list[str] = []
    if new is not None and current is not None and not limits.undo:
        if new > current * (HUNDRED + limits.increase_percent) / HUNDRED:
            reasons.append("increase_too_large")
        if new < current * (HUNDRED - limits.decrease_percent) / HUNDRED:
            reasons.append("decrease_too_large")
    if new is not None:
        if limits.minimum is None:
            reasons.append("minimum_not_checkable")
        elif new < limits.minimum:
            reasons.append("below_platform_minimum")
        if not limits.maximum_set:
            reasons.append("maximum_not_set")
        elif limits.maximum is None:
            reasons.append("maximum_not_checkable")
        elif new > limits.maximum:
            reasons.append("above_maximum")
        if limits.budget_changed_recently and not limits.undo:
            reasons.append("budget_changed_recently")
    if limits.volume_used >= limits.volume_limit:
        reasons.append("daily_limit_reached")
    return reasons


def run(facts: Facts) -> list[Check]:
    """Every check in order, with its result."""
    out: list[Check] = []
    failed = False

    def add(name: str, reasons: list[str]) -> None:
        nonlocal failed
        if failed:
            out.append(Check(name, "skipped"))
            return
        if reasons:
            out.extend(Check(name, "failed", r) for r in reasons)
            failed = True
        else:
            out.append(Check(name, "passed"))

    add("shape", [facts.params_reason] if facts.params is None and facts.params_reason else [])
    add("resource", [facts.resource_reason] if facts.resource_reason else [])
    snapshot, params = facts.snapshot, facts.params or {}
    budget = facts.spec.kind is ChangeKind.SET_DAILY_BUDGET
    new = Decimal(params["daily_budget"]) if budget and "daily_budget" in params else None
    if budget:
        reason = _budget_reason(snapshot, new) if snapshot and new is not None else None
        add("budget", [reason] if reason else [])
    current = snapshot.daily_budget if snapshot else None
    add("limits", _limit_reasons(facts.limits, current, new) if not failed else [])
    state = _state_reason(facts.spec, snapshot.status) if snapshot else "campaign_not_changeable"
    add("state", [state] if state else [])
    return out


def passed(checks: list[Check]) -> bool:
    return all(c.result == "passed" for c in checks)


def failures(checks: list[Check]) -> list[dict[str, Any]]:
    return [{"check": c.check, "reason": c.reason} for c in checks if c.result == "failed"]
