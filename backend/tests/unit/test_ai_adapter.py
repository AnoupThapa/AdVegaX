"""The Anthropic adapter and the prompt registry against the simulator (task 8-02)."""

from __future__ import annotations

import pytest
from app.domains.ai.adapter import (
    AiError,
    AiNotConfigured,
    AiTimedOut,
    AiUnavailable,
    ModelRequest,
)
from app.domains.ai.prompts import Prompt, register

from tests.ai_sim import MODEL, TEST_KEY, AiSim

SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}
REQUEST = ModelRequest(system="You plan campaigns.", prompt="Plan.", schema=SCHEMA, max_tokens=500)


def test_a_valid_answer_is_parsed_with_its_usage():
    sim = AiSim().queue({"summary": "Search first."})
    answer = sim.adapter().generate(REQUEST)
    assert (answer.data, answer.problem) == ({"summary": "Search first."}, None)
    assert (answer.input_tokens, answer.output_tokens) == (1200, 300)


def test_the_request_follows_the_messages_api_with_structured_outputs():
    sim = AiSim().queue({"summary": "x"})
    sim.adapter().generate(REQUEST)
    (request,) = sim.requests
    # The connection is pinned to the checked address; the host travels in the Host header.
    assert (request.method, request.headers["host"], request.url.path) == (
        "POST",
        "api.anthropic.com",
        "/v1/messages",
    )
    assert request.headers["x-api-key"] == TEST_KEY
    assert request.headers["anthropic-version"] == "2023-06-01"
    (body,) = sim.bodies()
    assert body == {
        "model": MODEL,
        "max_tokens": 500,
        "system": "You plan campaigns.",
        "messages": [{"role": "user", "content": "Plan."}],
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
    }
    assert "tools" not in body  # the model can only answer with data (A12)


@pytest.mark.parametrize(
    ("queued", "problem"),
    [("not_json", "not_json"), ("refusal", "refused"), ("max_tokens", "too_long")],
)
def test_unusable_answers_say_why(queued, problem):
    answer = AiSim().queue(queued).adapter().generate(REQUEST)
    assert (answer.data, answer.problem) == (None, problem)
    assert answer.input_tokens == 1200  # still paid for, so still counted


def test_a_json_answer_that_is_not_an_object_is_not_json():
    answer = AiSim().queue(["a", "list"]).adapter().generate(REQUEST)
    assert answer.problem == "not_json"


@pytest.mark.parametrize(
    ("queued", "error", "code"),
    [
        (429, AiUnavailable, "ai_unavailable"),
        (529, AiUnavailable, "ai_unavailable"),
        (500, AiUnavailable, "ai_unavailable"),
        (401, AiNotConfigured, "ai_key_refused"),
        (403, AiNotConfigured, "ai_key_refused"),
        (400, AiError, "ai_request_refused"),
        ("timeout", AiTimedOut, "ai_timed_out"),
    ],
)
def test_provider_failures_become_plain_errors(queued, error, code):
    sim = AiSim().queue(queued)
    with pytest.raises(error) as caught:
        sim.adapter().generate(REQUEST)
    assert caught.value.code == code
    assert TEST_KEY not in str(caught.value)


def test_without_a_key_nothing_is_called():
    sim = AiSim().queue({"summary": "x"})
    with pytest.raises(AiNotConfigured):
        sim.adapter(key=None).generate(REQUEST)
    assert sim.requests == []


def test_a_wrong_key_is_refused_by_the_provider():
    sim = AiSim().queue({"summary": "x"})
    with pytest.raises(AiNotConfigured) as caught:
        sim.adapter(key="sk-ant-wrong").generate(REQUEST)
    assert caught.value.code == "ai_key_refused"


# ------------------------------------------------------------------ prompts
def test_a_prompt_is_identified_by_its_hash():
    a = Prompt("t-hash", "v1", "System.", "Plan {product}.")
    assert len(a.template_hash) == 64
    assert a.template_hash != Prompt("t-hash", "v1", "System!", "Plan {product}.").template_hash
    assert a.render(product="gloves") == "Plan gloves."


def test_a_changed_prompt_needs_a_new_version():
    register(Prompt("t-version", "v1", "System.", "Plan."))
    register(Prompt("t-version", "v1", "System.", "Plan."))  # the same text is fine
    with pytest.raises(ValueError, match="without a new version"):
        register(Prompt("t-version", "v1", "System.", "Plan better."))
    register(Prompt("t-version", "v2", "System.", "Plan better."))
