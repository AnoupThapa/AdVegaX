"""The closed list of changes AdVegaX can make (Phase 10A, task 10A-02, Q-10A-1).

Three campaign-level changes on Google Ads and Meta. Each has typed values (``parse``), the
campaign states it applies to, and its opposite (``undo``). Anything not listed here cannot be
requested, by a person or (later) by a recommendation.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

from app.domains.finance.definitions import minor_units
from app.providers.base.changes import CampaignChange, CampaignSnapshot, ChangeKind
from app.providers.base.types import AdEntityStatus

MAX_AMOUNT = Decimal(10) ** 12  # far above any daily budget; the stored column's bound


@dataclass(frozen=True)
class ActionSpec:
    type: str
    kind: ChangeKind
    label: str
    # The campaign states (as the platform reports them now) in which the change makes sense.
    states: frozenset[AdEntityStatus]


CATALOGUE: dict[str, ActionSpec] = {
    "campaign.pause": ActionSpec(
        "campaign.pause", ChangeKind.PAUSE, "Pause the campaign", frozenset({AdEntityStatus.ACTIVE})
    ),
    "campaign.resume": ActionSpec(
        "campaign.resume",
        ChangeKind.RESUME,
        "Resume the campaign",
        frozenset({AdEntityStatus.PAUSED}),
    ),
    "campaign.set_daily_budget": ActionSpec(
        "campaign.set_daily_budget",
        ChangeKind.SET_DAILY_BUDGET,
        "Set the daily budget",
        frozenset({AdEntityStatus.ACTIVE, AdEntityStatus.PAUSED}),
    ),
}


class ParamsInvalid(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def quantum(currency: str) -> Decimal:
    return Decimal(1).scaleb(-minor_units(currency))


def parse(spec: ActionSpec, raw: dict[str, Any], currency: str) -> dict[str, str]:
    """The change's values in their stored form, or ``ParamsInvalid`` with a plain reason."""
    if spec.kind is not ChangeKind.SET_DAILY_BUDGET:
        if raw:
            raise ParamsInvalid("unexpected_values")
        return {}
    if set(raw) != {"daily_budget"}:
        raise ParamsInvalid("daily_budget_required")
    value = raw["daily_budget"]
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        raise ParamsInvalid("daily_budget_invalid")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ParamsInvalid("daily_budget_invalid") from None
    if not amount.is_finite() or amount <= 0 or amount >= MAX_AMOUNT:
        raise ParamsInvalid("daily_budget_invalid")
    step = quantum(currency)
    if amount != amount.quantize(step, rounding=ROUND_HALF_EVEN):
        raise ParamsInvalid("daily_budget_precision")
    return {"daily_budget": str(amount.quantize(step))}


def change_of(spec: ActionSpec, params: dict[str, str]) -> CampaignChange:
    amount = params.get("daily_budget")
    return CampaignChange(spec.kind, Decimal(amount) if amount is not None else None)


def key(campaign_id: uuid.UUID, spec: ActionSpec, params: dict[str, str]) -> str:
    """Identifies the change: the same campaign, type and values give the same key."""
    text = json.dumps([str(campaign_id), spec.type, params], sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def undo(spec: ActionSpec, previous: dict[str, Any]) -> tuple[ActionSpec, dict[str, str]] | None:
    """The opposite change, from the campaign as it was before (None: nothing to undo)."""
    if spec.kind is ChangeKind.PAUSE:
        return CATALOGUE["campaign.resume"], {}
    if spec.kind is ChangeKind.RESUME:
        return CATALOGUE["campaign.pause"], {}
    before = previous.get("daily_budget")
    if before is None:
        return None
    return CATALOGUE["campaign.set_daily_budget"], {"daily_budget": str(before)}


def reached(spec: ActionSpec, params: dict[str, str], snapshot: CampaignSnapshot) -> bool:
    """Whether the campaign, as read now, shows the change as made."""
    if spec.kind is ChangeKind.PAUSE:
        return snapshot.status is AdEntityStatus.PAUSED
    if spec.kind is ChangeKind.RESUME:
        return snapshot.status is AdEntityStatus.ACTIVE
    wanted = Decimal(params["daily_budget"])
    return snapshot.daily_budget is not None and snapshot.daily_budget == wanted


def same_state(before: dict[str, Any], now: CampaignSnapshot) -> bool:
    """Whether the campaign is still as it was when the change was requested (the fields a
    change depends on)."""
    current = now.as_json()
    fields = ("status", "budget_level", "budget_period", "budget_shared")
    if any(before.get(f) != current.get(f) for f in fields):
        return False
    old, new = before.get("daily_budget"), current.get("daily_budget")
    if old is None or new is None:
        return old == new
    return Decimal(old) == Decimal(new)
