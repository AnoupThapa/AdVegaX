"""Running a model task: limits, one retry, and the recorded run (task 8-02, PLAN Q-8-8)."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from app.core.errors import AiAnswerRejected, AiLimitReached, AiUnavailableError
from app.domains.ai.prompts import Prompt
from app.domains.ai.runs import Task, adapter_for, estimated_cost, run_task
from sqlalchemy import text

from tests.ai_sim import TEST_KEY, AiSim

PROMPT = Prompt("test-plan", "v1", "You plan campaigns.", "Plan for {product}.")
SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


def _validate(data):
    return [] if data.get("summary", "").strip() else ["summary_empty"]


TASK = Task(
    name="campaign_strategy",
    prompt=PROMPT,
    parts={"product": "gloves"},
    schema=SCHEMA,
    snapshot={"product": {"title": "Gloves"}, "figures": {"orders": "12"}},
    validate=_validate,
)


@pytest.fixture
def ai(runtime):
    sim = AiSim()
    runtime.settings = runtime.settings.model_copy(update={"AI_ENABLED": True})
    runtime.extras["ai_adapter"] = sim.adapter()
    return sim


@pytest.fixture
def org(make_client):
    c = make_client()
    c.signup(f"ai-{uuid.uuid4().hex[:6]}@example.com")
    return uuid.UUID(c.create_org("Plan Co")["id"])


def _runs(admin_engine, org_id):
    with admin_engine.connect() as db:
        return [
            dict(r._mapping)
            for r in db.execute(
                text(
                    "SELECT r.*, m.provider, m.model_name, p.name AS prompt_name, "
                    "p.version AS prompt_version, p.template_hash "
                    "FROM ai_runs r JOIN ai_models m ON m.id = r.model_id "
                    "JOIN prompt_versions p ON p.id = r.prompt_version_id "
                    "WHERE r.organization_id = :o ORDER BY r.created_at"
                ),
                {"o": org_id},
            )
        ]


def test_a_good_answer_is_returned_and_recorded(runtime, ai, org, admin_engine):
    ai.queue({"summary": "Search first, then social."})
    outcome = run_task(runtime, organization_id=org, user_id=None, task=TASK)
    assert outcome.data == {"summary": "Search first, then social."}
    (run,) = _runs(admin_engine, org)
    assert run["id"] == outcome.run_id
    assert (run["status"], run["attempts"], run["task"]) == ("succeeded", 1, "campaign_strategy")
    assert (run["provider"], run["model_name"]) == ("anthropic", "claude-sonnet-5-5")
    assert (run["prompt_name"], run["prompt_version"]) == ("test-plan", "v1")
    assert run["template_hash"] == PROMPT.template_hash
    assert run["context_snapshot"] == TASK.snapshot
    assert run["output_json"] == outcome.data
    assert (run["input_tokens"], run["output_tokens"]) == (1200, 300)
    assert run["estimated_cost"] is None  # no price configured: unknown, never 0
    assert run["rejection_reasons"] is None
    assert run["created_at"] == runtime.clock.now()
    (body,) = ai.bodies()
    assert body["messages"][0]["content"] == "Plan for gloves."


def test_an_invalid_answer_is_retried_once_with_the_reasons(runtime, ai, org, admin_engine):
    ai.queue({"summary": " "}, {"summary": "Fixed."})
    outcome = run_task(runtime, organization_id=org, user_id=None, task=TASK)
    assert outcome.data == {"summary": "Fixed."}
    first, second = ai.bodies()
    assert "summary_empty" not in first["messages"][0]["content"]
    assert "summary_empty" in second["messages"][0]["content"]
    (run,) = _runs(admin_engine, org)
    assert (run["status"], run["attempts"]) == ("succeeded", 2)
    assert (run["input_tokens"], run["output_tokens"]) == (2400, 600)  # both calls counted


def test_two_invalid_answers_are_rejected_with_plain_reasons(runtime, ai, org, admin_engine):
    ai.queue("not_json", {"summary": ""})
    with pytest.raises(AiAnswerRejected) as caught:
        run_task(runtime, organization_id=org, user_id=None, task=TASK)
    assert caught.value.details == [{"reason": "summary_empty"}]
    assert len(ai.requests) == 2  # never more than one retry
    (run,) = _runs(admin_engine, org)
    assert (run["status"], run["attempts"], run["output_json"]) == ("rejected", 2, None)
    assert run["rejection_reasons"] == ["summary_empty"]


@pytest.mark.parametrize(
    ("queued", "status", "reason"),
    [("refusal", "rejected", "answer_refused"), ("max_tokens", "rejected", "answer_too_long")],
)
def test_refused_and_cut_off_answers(runtime, ai, org, admin_engine, queued, status, reason):
    ai.queue(queued, queued)
    with pytest.raises(AiAnswerRejected):
        run_task(runtime, organization_id=org, user_id=None, task=TASK)
    (run,) = _runs(admin_engine, org)
    assert (run["status"], run["rejection_reasons"]) == (status, [reason])


@pytest.mark.parametrize(
    ("queued", "status", "reason"),
    [
        (529, "failed", "ai_unavailable"),
        (429, "failed", "ai_unavailable"),
        ("timeout", "timed_out", "ai_timed_out"),
    ],
)
def test_provider_failures_are_recorded_and_not_retried(
    runtime, ai, org, admin_engine, queued, status, reason
):
    ai.queue(queued, {"summary": "never asked"})
    with pytest.raises(AiUnavailableError):
        run_task(runtime, organization_id=org, user_id=None, task=TASK)
    assert len(ai.requests) == 1
    (run,) = _runs(admin_engine, org)
    assert (run["status"], run["rejection_reasons"], run["output_json"]) == (
        status,
        [reason],
        None,
    )


def test_switched_off_or_without_a_key_nothing_is_called(runtime, ai, org, admin_engine):
    runtime.settings = runtime.settings.model_copy(update={"AI_ENABLED": False})
    with pytest.raises(AiUnavailableError):
        run_task(runtime, organization_id=org, user_id=None, task=TASK)
    runtime.settings = runtime.settings.model_copy(update={"AI_ENABLED": True})
    runtime.extras["ai_adapter"] = ai.adapter(key=None)
    with pytest.raises(AiUnavailableError):
        run_task(runtime, organization_id=org, user_id=None, task=TASK)
    assert ai.requests == []
    assert _runs(admin_engine, org) == []


def test_the_daily_limit_counts_every_run_and_resets_each_utc_day(runtime, ai, org, admin_engine):
    runtime.settings = runtime.settings.model_copy(update={"AI_DAILY_RUNS": 2})
    ai.queue(529, {"summary": "ok"})
    with pytest.raises(AiUnavailableError):
        run_task(runtime, organization_id=org, user_id=None, task=TASK)
    run_task(runtime, organization_id=org, user_id=None, task=TASK)
    with pytest.raises(AiLimitReached):
        run_task(runtime, organization_id=org, user_id=None, task=TASK)
    assert len(ai.requests) == 2
    runtime.clock.advance(timedelta(days=1))
    ai.queue({"summary": "next day"})
    assert run_task(runtime, organization_id=org, user_id=None, task=TASK).data == {
        "summary": "next day"
    }


def test_the_limit_is_per_organization(runtime, ai, org, make_client):
    runtime.settings = runtime.settings.model_copy(update={"AI_DAILY_RUNS": 1})
    ai.queue({"summary": "a"}, {"summary": "b"})
    run_task(runtime, organization_id=org, user_id=None, task=TASK)
    c = make_client()
    c.signup(f"ai-other-{uuid.uuid4().hex[:6]}@example.com")
    other = uuid.UUID(c.create_org("Other Co")["id"])
    assert run_task(runtime, organization_id=other, user_id=None, task=TASK).data == {
        "summary": "b"
    }


def test_reference_rows_are_shared_between_runs(runtime, ai, org, admin_engine):
    ai.queue({"summary": "a"}, {"summary": "b"})
    run_task(runtime, organization_id=org, user_id=None, task=TASK)
    run_task(runtime, organization_id=org, user_id=None, task=TASK)
    with admin_engine.connect() as db:
        counts = db.execute(
            text("SELECT (SELECT count(*) FROM ai_models), (SELECT count(*) FROM prompt_versions)")
        ).one()
    assert tuple(counts) == (1, 1)


def test_a_prompt_changed_without_a_new_version_is_refused(runtime, ai, org):
    ai.queue({"summary": "a"}, {"summary": "b"})
    run_task(runtime, organization_id=org, user_id=None, task=TASK)
    changed = Task(
        name=TASK.name,
        prompt=Prompt("test-plan", "v1", "You plan campaigns.", "Plan better for {product}."),
        parts=TASK.parts,
        schema=SCHEMA,
        snapshot=TASK.snapshot,
        validate=_validate,
    )
    with pytest.raises(ValueError, match="without a new version"):
        run_task(runtime, organization_id=org, user_id=None, task=changed)


def test_the_cost_is_estimated_from_configured_prices(runtime, ai, org, admin_engine):
    runtime.settings = runtime.settings.model_copy(
        update={"AI_PRICE_INPUT_PER_MTOK": Decimal("3"), "AI_PRICE_OUTPUT_PER_MTOK": Decimal("15")}
    )
    ai.queue({"summary": "a"})
    run_task(runtime, organization_id=org, user_id=None, task=TASK)
    (run,) = _runs(admin_engine, org)
    assert run["estimated_cost"] == Decimal("0.008100")  # 1,200 x 3 + 300 x 15 per million
    assert estimated_cost(runtime.settings, 0, 0) == Decimal("0")


def test_the_key_never_reaches_the_records_or_the_logs(runtime, ai, org, admin_engine, caplog):
    ai.queue("not_json", 529)
    with caplog.at_level(logging.DEBUG), pytest.raises(AiUnavailableError):
        run_task(runtime, organization_id=org, user_id=None, task=TASK)
    assert TEST_KEY not in caplog.text
    assert TEST_KEY not in str(_runs(admin_engine, org))


def test_runs_are_tenant_scoped(runtime, ai, org, make_client):
    ai.queue({"summary": "a"})
    run_task(runtime, organization_id=org, user_id=None, task=TASK)
    c = make_client()
    c.signup(f"ai-peek-{uuid.uuid4().hex[:6]}@example.com")
    other = uuid.UUID(c.create_org("Peek Co")["id"])
    with runtime.db.transaction(org_id=other) as session:
        assert session.execute(text("SELECT count(*) FROM ai_runs")).scalar_one() == 0
    with runtime.db.transaction(org_id=org) as session:
        assert session.execute(text("SELECT count(*) FROM ai_runs")).scalar_one() == 1


def test_the_default_adapter_is_anthropic_with_the_ai_time_limit(runtime):
    runtime.extras.pop("ai_adapter", None)
    adapter = adapter_for(runtime)
    assert (adapter.provider, adapter.model) == ("anthropic", runtime.settings.AI_MODEL)
