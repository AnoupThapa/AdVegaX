"""Running a model task and recording it (Phase 8, task 8-02, PLAN Q-8-8, §6; A26).

``run_task`` is the only way AdVegaX calls a model:

1. **Switched on and within the limit.** ``AI_ENABLED`` must be on and the organization must
   have runs left today (``AI_DAILY_RUNS`` per UTC day; every recorded run counts, whatever its
   outcome, because every one was a paid call). Otherwise nothing is called.
2. **One answer, checked.** The adapter returns JSON constrained to the task's schema; the task's
   own ``validate`` (8-04) returns plain reasons when it is not acceptable. An answer that is
   not JSON, was refused, was cut off or failed the checks is asked for once more
   (``AI_MAX_RETRIES``), with the reasons — never the model's own text — added to the request.
3. **Always recorded.** Every call, successful or not, becomes one ``ai_runs`` row with the
   model, prompt version and hash, the data snapshot sent, outcome, reasons, tokens, estimated
   cost and time. The model call itself runs **outside** any database transaction.

The key is never recorded, logged or returned; failures carry plain message keys only.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import AiAnswerRejected, AiLimitReached, AiUnavailableError
from app.core.settings import Settings
from app.domains.ai.adapter import AiError, AiTimedOut, ModelAdapter, ModelRequest
from app.domains.ai.anthropic import AnthropicAdapter
from app.domains.ai.models import AiModel, AiRun, PromptVersion
from app.domains.ai.prompts import Prompt
from app.domains.billing import entitlements
from app.providers.http.client import SafeHttpClient
from app.runtime import Runtime, outbound_policy

logger = logging.getLogger("advegax.ai")

MTOK = Decimal(1_000_000)
COST_PLACES = Decimal("0.000001")
Validate = Callable[[dict[str, Any]], list[str]]  # [] = acceptable; else plain reason keys

CORRECTION = (
    "\n\nYour previous answer was not accepted for these reasons: {reasons}. "
    "Answer again, following the schema and the rules above."
)


@dataclass(frozen=True)
class Task:
    name: str  # one of ``RUN_TASKS``
    prompt: Prompt
    parts: dict[str, str]  # fills the prompt's template
    schema: dict[str, Any]
    snapshot: dict[str, Any]  # what is recorded as sent: AdVegaX's own figures only
    validate: Validate


@dataclass(frozen=True)
class Outcome:
    run_id: uuid.UUID
    data: dict[str, Any]


def adapter_for(rt: Runtime) -> ModelAdapter:
    """The configured model adapter (tests put a simulated one in ``rt.extras["ai_adapter"]``)."""
    injected = rt.extras.get("ai_adapter")
    if injected is not None:
        return injected  # type: ignore[return-value]
    seconds = rt.settings.AI_TIMEOUT.total_seconds()
    policy = replace(outbound_policy(rt.settings), read_timeout=seconds, request_timeout=seconds)
    return AnthropicAdapter(
        rt.settings.ANTHROPIC_API_KEY, rt.settings.AI_MODEL, lambda: SafeHttpClient(policy)
    )


def runs_today(session: Session, organization_id: uuid.UUID, now: datetime) -> int:
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return session.execute(
        select(func.count())
        .select_from(AiRun)
        .where(AiRun.organization_id == organization_id, AiRun.created_at >= start)
    ).scalar_one()


def estimated_cost(settings: Settings, tokens_in: int, tokens_out: int) -> Decimal | None:
    """USD, from the configured prices per million tokens; None when no price is set (the
    usage view then says "No price set", never 0)."""
    price_in, price_out = settings.AI_PRICE_INPUT_PER_MTOK, settings.AI_PRICE_OUTPUT_PER_MTOK
    if price_in is None or price_out is None:
        return None
    cost = (Decimal(tokens_in) * price_in + Decimal(tokens_out) * price_out) / MTOK
    return cost.quantize(COST_PLACES)


def _reference_ids(session: Session, adapter: ModelAdapter, prompt: Prompt) -> tuple[Any, Any]:
    session.execute(
        insert(AiModel)
        .values(id=uuid.uuid4(), provider=adapter.provider, model_name=adapter.model)
        .on_conflict_do_nothing(constraint="uq_ai_models_provider_model")
    )
    model_id = session.execute(
        select(AiModel.id).where(
            AiModel.provider == adapter.provider, AiModel.model_name == adapter.model
        )
    ).scalar_one()
    session.execute(
        insert(PromptVersion)
        .values(
            id=uuid.uuid4(),
            name=prompt.name,
            version=prompt.version,
            template_hash=prompt.template_hash,
        )
        .on_conflict_do_nothing(constraint="uq_prompt_versions_name_version")
    )
    version_id, stored_hash = session.execute(
        select(PromptVersion.id, PromptVersion.template_hash).where(
            PromptVersion.name == prompt.name, PromptVersion.version == prompt.version
        )
    ).one()
    if stored_hash != prompt.template_hash:
        # A deployed prompt text changed without a new version: refuse rather than mislabel.
        raise ValueError(f"prompt {prompt.name} {prompt.version} changed without a new version")
    return model_id, version_id


def run_task(
    rt: Runtime, *, organization_id: uuid.UUID, user_id: uuid.UUID | None, task: Task
) -> Outcome:
    """Call the model for ``task`` and record the run. Raises ``AiLimitReached`` (429),
    ``AiUnavailableError`` (503) or ``AiAnswerRejected`` (422, ``details`` = reasons)."""
    settings = rt.settings
    if not settings.AI_ENABLED:
        raise AiUnavailableError()
    with rt.db.transaction(org_id=organization_id) as session:
        # Phase 13 (Q-13-8): the plan's daily runs when lower; none while read-only.
        entitlements.require_writable(rt, session, organization_id)
        allowed = entitlements.ai_runs_allowed(rt, session, organization_id)
        if runs_today(session, organization_id, rt.clock.now()) >= allowed:
            raise AiLimitReached()
    adapter = adapter_for(rt)

    attempts, tokens_in, tokens_out = 0, 0, 0
    reasons: list[str] = []
    data: dict[str, Any] | None = None
    status = "failed"
    started = time.perf_counter()
    base = task.prompt.render(**task.parts)
    prompt = base
    while attempts <= settings.AI_MAX_RETRIES:
        attempts += 1
        try:
            answer = adapter.generate(
                ModelRequest(
                    system=task.prompt.system,
                    prompt=prompt,
                    schema=task.schema,
                    max_tokens=settings.AI_MAX_OUTPUT_TOKENS,
                )
            )
        except AiTimedOut:
            status, reasons, data = "timed_out", ["ai_timed_out"], None
            break
        except AiError as exc:
            if exc.code == "ai_not_configured" and attempts == 1:
                raise AiUnavailableError() from None  # no key: nothing was called or spent
            status, reasons, data = "failed", [exc.code], None
            break
        tokens_in += answer.input_tokens
        tokens_out += answer.output_tokens
        if answer.data is None:
            reasons = [f"answer_{answer.problem or 'not_json'}"]
        else:
            reasons = task.validate(answer.data)
        if not reasons:
            status, data = "succeeded", answer.data
            break
        status, data = "rejected", None
        prompt = base + CORRECTION.format(reasons=", ".join(reasons))
    latency_ms = int((time.perf_counter() - started) * 1000)

    with rt.db.transaction(org_id=organization_id) as session:
        model_id, version_id = _reference_ids(session, adapter, task.prompt)
        run = AiRun(
            organization_id=organization_id,
            user_id=user_id,
            model_id=model_id,
            prompt_version_id=version_id,
            task=task.name,
            context_snapshot=task.snapshot,
            status=status,
            output_json=data,
            rejection_reasons=reasons or None,
            attempts=attempts,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            estimated_cost=estimated_cost(settings, tokens_in, tokens_out),
            latency_ms=latency_ms,
            created_at=rt.clock.now(),
        )
        session.add(run)
        session.flush()
        run_id = run.id
    logger.info(
        "ai_run",
        extra={"run_id": str(run_id), "status": status, "attempts": attempts, "task": task.name},
    )
    if status == "succeeded" and data is not None:
        return Outcome(run_id, data)
    if status == "rejected":
        raise AiAnswerRejected(details=[{"reason": r} for r in reasons])
    raise AiUnavailableError()
