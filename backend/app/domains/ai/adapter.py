"""The model adapter (Phase 8, task 8-02, PLAN Q-8-1).

The planner never talks to a model provider directly: it asks an adapter for **one answer
constrained to a JSON schema**. Adapters are swappable (D19) — the first one is Anthropic's
(``anthropic.py``); tests use the simulator (``tests/ai_sim.py``). An adapter has **no tools**:
the model can only answer with data, which AdVegaX validates before anything uses it (A12).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelRequest:
    system: str  # AdVegaX's fixed instructions (a versioned prompt)
    prompt: str  # the task with its data; untrusted text inside is delimited (8-03)
    schema: dict[str, Any]  # the JSON schema the answer must follow
    max_tokens: int


@dataclass(frozen=True)
class ModelAnswer:
    """What the model said. ``data`` is the parsed JSON object, or None when the answer was not
    one (``problem`` says why: ``not_json``, ``refused``, ``too_long``)."""

    data: dict[str, Any] | None
    problem: str | None
    input_tokens: int
    output_tokens: int


class AiError(Exception):
    """A call that did not produce an answer. ``code`` is a plain message key."""

    code = "ai_failed"

    def __init__(self, code: str | None = None) -> None:
        super().__init__(code or self.code)
        if code:
            self.code = code


class AiNotConfigured(AiError):
    code = "ai_not_configured"


class AiUnavailable(AiError):
    code = "ai_unavailable"  # the provider is down, overloaded or limiting AdVegaX


class AiTimedOut(AiError):
    code = "ai_timed_out"


class ModelAdapter(Protocol):
    provider: str
    model: str

    def generate(self, request: ModelRequest) -> ModelAnswer: ...
