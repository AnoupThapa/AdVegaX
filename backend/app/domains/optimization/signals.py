"""The five fixed rules (Phase 11, task 11-02, PHASE_11_PLAN Q-11-1, Q-11-3; A30).

No AI here. Each running campaign is compared **with its own past**: the last
``OPTIMIZATION_RECENT_DAYS`` full days against the ``OPTIMIZATION_BASELINE_DAYS`` before them.
Every figure is AdVegaX's own (Phase 6), in the organization's reporting currency.

1. **Spend without results** — spent at least the minimum, no conversions.
2. **Losing money** — the platform's conversion value per unit of spend is below the
   **break-even** level, ``1 / gross margin`` (Phase 6, from the products sold in the same days).
3. **Held back by budget** — uses at least ``OPTIMIZATION_BUDGET_USE`` of its daily budget while
   its conversion value is at least ``OPTIMIZATION_WINNER_FACTOR`` times the break-even level.
4. **Cost per conversion jumped** — at least ``cost_jump_percent`` higher than its own
   baseline.
5. **Funnel drop-off** — Phase 7's findings for the whole business and each ad platform.

A rule never fires on a missing figure (never treated as 0), below the minimum spend, or — for
rules 2 to 4 — with fewer than ``min_conversions`` conversions in the baseline. The profit rules
(2, 3) need a gross margin known for at least ``OPTIMIZATION_MARGIN_COVERAGE`` of net sales.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.domains.funnel.findings import Finding
from app.domains.metrics.engine import Figure

ZERO = Decimal(0)
HUNDRED = Decimal(100)
RECENT_KEYS = (
    "spend",
    "clicks",
    "conversions",
    "conversion_value",
    "platform_roas",
    "cost_per_conversion",
    "budget_use",
)
BASELINE_KEYS = ("spend", "conversions", "cost_per_conversion", "platform_roas")


@dataclass(frozen=True)
class Thresholds:
    min_spend: Decimal  # reporting currency, over the recent days
    min_conversions: int  # in the baseline days (rules 2 to 4)
    budget_step_percent: int
    cost_jump_percent: int
    budget_use: Decimal
    winner_factor: Decimal
    margin_coverage: Decimal


@dataclass(frozen=True)
class Margin:
    """The business's gross margin over the recent days, or why it cannot be used."""

    value: Decimal | None
    coverage: Decimal | None
    reason: str | None  # None: usable

    @property
    def break_even(self) -> Decimal | None:
        if self.reason is not None or self.value is None or self.value <= ZERO:
            return None
        return Decimal(1) / self.value


@dataclass(frozen=True)
class CampaignInput:
    id: uuid.UUID
    ad_account_id: uuid.UUID
    provider: str
    name: str
    status: str
    recent: Mapping[str, Figure]
    baseline: Mapping[str, Figure]


@dataclass(frozen=True)
class Signal:
    kind: str
    fingerprint: str
    campaign_id: uuid.UUID | None
    ad_account_id: uuid.UUID | None
    figures: dict[str, Any]  # what the advice rests on (strings; None = not available)
    weight: Decimal  # the money at stake, for the order when the AI does not rank
    facts: dict[str, Any] = field(default_factory=dict)


def _value(figure: Figure | None) -> Decimal | None:
    return figure.value if figure is not None and figure.ok else None


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def margin_of(sales: Iterable[tuple[Figure, Figure]], coverage_needed: Decimal) -> Margin:
    """From (net sales, gross profit) per product: the margin of the products whose cost is
    known, and the share of net sales they make."""
    total = known_sales = known_profit = ZERO
    for net, profit in sales:
        amount = _value(net)
        if amount is None or amount <= ZERO:
            continue
        total += amount
        gained = _value(profit)
        if gained is not None:
            known_sales += amount
            known_profit += gained
    if total <= ZERO:
        return Margin(None, None, "no_sales")
    coverage = known_sales / total
    if known_sales <= ZERO or coverage < coverage_needed:
        return Margin(None, coverage, "costs_missing")
    margin = known_profit / known_sales
    if margin <= ZERO:
        return Margin(margin, coverage, "no_margin")
    return Margin(margin, coverage, None)


def _figures(c: CampaignInput, margin: Margin) -> dict[str, Any]:
    out: dict[str, Any] = {f"recent.{k}": _text(_value(c.recent.get(k))) for k in RECENT_KEYS}
    out.update({f"baseline.{k}": _text(_value(c.baseline.get(k))) for k in BASELINE_KEYS})
    out["gross_margin"] = _text(margin.value) if margin.reason is None else None
    out["break_even_roas"] = _text(margin.break_even)
    return out


def evaluate(c: CampaignInput, margin: Margin, t: Thresholds) -> list[Signal]:
    """The rules that fire for one campaign (none for a campaign that is not running)."""
    if c.status != "active":
        return []
    spend = _value(c.recent.get("spend"))
    if spend is None or spend < t.min_spend:
        return []
    conversions = _value(c.recent.get("conversions"))
    if conversions is None:
        return []
    figures = _figures(c, margin)
    found: list[Signal] = []

    def add(kind: str, **facts: Any) -> None:
        found.append(
            Signal(
                kind=kind,
                fingerprint=f"{kind}:{c.id}",
                campaign_id=c.id,
                ad_account_id=c.ad_account_id,
                figures=figures,
                weight=spend,
                facts=facts,
            )
        )

    if conversions == ZERO:
        add("spend_without_results", loss=_text(spend))
        return found
    history = _value(c.baseline.get("conversions"))
    if history is None or history < t.min_conversions:
        return found
    roas = _value(c.recent.get("platform_roas"))
    even = margin.break_even
    if even is not None and roas is not None:
        value = _value(c.recent.get("conversion_value"))
        if roas < even and value is not None and margin.value is not None:
            add("losing_money", loss=_text(spend - value * margin.value))
        use = _value(c.recent.get("budget_use"))
        if use is not None and use >= t.budget_use and roas >= even * t.winner_factor:
            add("budget_limited")
    cost, usual = (
        _value(c.recent.get("cost_per_conversion")),
        _value(c.baseline.get("cost_per_conversion")),
    )
    if (
        cost is not None
        and usual is not None
        and usual > ZERO
        and cost >= usual * (HUNDRED + t.cost_jump_percent) / HUNDRED
    ):
        add("cost_jump", increase=_text((cost / usual - 1) * HUNDRED))
    return found


def funnel_signals(findings: Iterable[Finding]) -> list[Signal]:
    """Phase 7's drop-offs, for the whole business and each ad platform (channel names are
    free text from Google Analytics and are left out)."""
    out = []
    for f in findings:
        if f.view not in ("whole", "platform"):
            continue
        subject = f.subject or "business"
        out.append(
            Signal(
                kind="funnel_drop",
                fingerprint=f"funnel_drop:{f.view}:{subject}:{f.from_stage}:{f.to_stage}",
                campaign_id=None,
                ad_account_id=None,
                figures={
                    "rate": _text(f.rate),
                    "previous_rate": _text(f.previous_rate),
                    "baseline_rate": _text(f.baseline_rate),
                    "change": _text(f.change),
                    "events_before": _text(f.events_before),
                },
                weight=ZERO,
                facts={
                    "view": f.view,
                    "platform": f.subject if f.view == "platform" else None,
                    "from_stage": f.from_stage,
                    "to_stage": f.to_stage,
                },
            )
        )
    return out
