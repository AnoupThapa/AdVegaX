"""Drop-off findings (Phase 7, task 7-05, PHASE_07_PLAN Q-7-7; A25).

Fixed rules, no AI: a business is compared **with itself**, never with benchmarks. A step is
flagged when, for the period:

1. both its stages come from the same source (a step across sources has no rate to judge);
2. its earlier stage had at least ``FUNNEL_MIN_EVENTS`` events (small numbers never alarm);
3. its rate is at least ``FUNNEL_DROP_SHARE`` lower than in the **previous period of equal
   length**; and
4. its rate is lower than its **own average over the ``FUNNEL_BASELINE_DAYS`` before the
   period**.

Every rate involved must be available: a step with a missing day, a stage not provided or a
zero divisor is never flagged. Applied to the whole business, each ad platform's own funnel and
each Google Analytics channel. The findings carry their numbers, so the web app can say them in
plain words and Phase 8 / 11 can read them later.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.settings import Settings
from app.domains.funnel.engine import (
    FunnelDay,
    FunnelInputs,
    StepFigure,
    channels,
    platforms,
    whole,
)
from app.domains.metrics.engine import Figure, Scope


@dataclass(frozen=True)
class Rules:
    drop_share: Decimal  # e.g. 0.25: at least 25 % lower than the previous period
    min_events: int  # the earlier stage's events in the period
    baseline_days: int  # the "own average" window before the period


@dataclass(frozen=True)
class Finding:
    view: str  # whole | platform | channel
    subject: str | None  # the platform code or channel name; None for the whole business
    from_stage: str
    to_stage: str
    rate: Decimal
    previous_rate: Decimal
    baseline_rate: Decimal
    events_before: Decimal  # the earlier stage's events in the period
    change: Decimal  # relative change against the previous period (negative: a fall)


def _shift(day: date, days: int) -> date:
    return date.fromordinal(day.toordinal() + days)


Funnel = tuple[dict[str, Figure], list[StepFigure]]
Views = dict[tuple[str, str | None], Funnel]


def _views(scope: Scope) -> Callable[[FunnelDay], Views]:
    """Every funnel of a period, by (view, subject)."""

    def read(day: FunnelDay) -> Views:
        found: Views = {("whole", None): whole(scope, day)}
        for provider, _, stages, steps in platforms(scope, day):
            found[("platform", provider)] = (stages, steps)
        listed, _ = channels(scope, day)
        for name, stages, steps in listed:
            found[("channel", name)] = (stages, steps)
        return found

    return read


def _rates(funnel: Funnel | None) -> dict[tuple[str, str], Figure | None]:
    if funnel is None:
        return {}
    return {(s.step.from_stage, s.step.to_stage): s.rate for s in funnel[1]}


def rules_from(settings: Settings) -> Rules:
    return Rules(
        drop_share=Decimal(settings.FUNNEL_DROP_SHARE),
        min_events=settings.FUNNEL_MIN_EVENTS,
        baseline_days=settings.FUNNEL_BASELINE_DAYS,
    )


def find_drop_offs(
    scope: Scope, funnel: FunnelInputs, first: date, last: date, rules: Rules
) -> list[Finding]:
    """The findings of ``first`` … ``last``. ``funnel`` must also cover the previous period and
    the baseline window before ``first`` (days it does not cover count as not read)."""
    span = last.toordinal() - first.toordinal() + 1
    read = _views(scope)
    current = read(funnel.period(first, last))
    previous = read(funnel.period(_shift(first, -span), _shift(first, -1)))
    baseline = read(funnel.period(_shift(first, -rules.baseline_days), _shift(first, -1)))
    covered = funnel.first <= _shift(first, -max(span, rules.baseline_days))
    if not covered:
        return []
    found: list[Finding] = []
    for key, (stages, steps) in current.items():
        before = _rates(previous.get(key))
        average = _rates(baseline.get(key))
        for step in steps:
            if step.step.kind != "same_source" or step.rate is None or not step.rate.ok:
                continue
            pair = (step.step.from_stage, step.step.to_stage)
            earlier = stages[step.step.from_stage]
            old, usual = before.get(pair), average.get(pair)
            if old is None or usual is None or not old.ok or not usual.ok:
                continue
            rate, was, normal, events = step.rate.value, old.value, usual.value, earlier.value
            if rate is None or was is None or normal is None or events is None:
                continue
            if events < rules.min_events or was == 0:
                continue
            if rate > was * (1 - rules.drop_share) or rate >= normal:
                continue
            change = ((rate - was) / was).quantize(Decimal("0.0001"))
            found.append(
                Finding(
                    view=key[0],
                    subject=key[1],
                    from_stage=pair[0],
                    to_stage=pair[1],
                    rate=rate,
                    previous_rate=was,
                    baseline_rate=normal,
                    events_before=events,
                    change=change,
                )
            )
    found.sort(key=lambda f: (f.change, f.view, f.subject or "", f.from_stage))
    return found
