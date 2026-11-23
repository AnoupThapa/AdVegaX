"""One planning request as a model task (Phase 8, task 8-04): the prompt filled with the context,
the answer schema, the snapshot recorded with the run, and the validation chain."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.domains.ai.runs import Task
from app.domains.strategy.context import PlanningContext
from app.domains.strategy.prompt import CAMPAIGN_STRATEGY
from app.domains.strategy.schema import ANSWER_SCHEMA
from app.domains.strategy.validation import StrategyRequest, validate


def describe_budget(request: StrategyRequest) -> str:
    b = request.budget
    return f"{b.amount} {b.currency} per {'day' if b.period == 'daily' else 'month'}"


def strategy_task(
    context: PlanningContext,
    request: StrategyRequest,
    *,
    minimums: dict[str, Decimal | None],
    target_factor: Decimal,
) -> Task:
    def check(answer: dict[str, Any]) -> list[str]:
        return validate(answer, context, request, minimums=minimums, target_factor=target_factor)

    parts = context.prompt_parts()
    return Task(
        name="campaign_strategy",
        prompt=CAMPAIGN_STRATEGY,
        parts={
            "platforms": ", ".join(request.platforms),
            "objective": request.objective or "choose sales, leads or awareness",
            "budget": describe_budget(request),
            **parts,
        },
        schema=ANSWER_SCHEMA,
        snapshot={
            **context.snapshot(),
            "request": {
                "platforms": list(request.platforms),
                "objective": request.objective,
                "budget": {
                    "amount": str(request.budget.amount),
                    "period": request.budget.period,
                    "currency": request.budget.currency,
                },
            },
        },
        validate=check,
    )
