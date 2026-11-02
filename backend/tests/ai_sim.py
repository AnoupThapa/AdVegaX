"""A recorded-format Claude Messages API for tests (Phase 8, task 8-02).

Answers like ``POST https://api.anthropic.com/v1/messages`` with structured outputs, as
documented (checked 2026-10-25; Step 0 confirms it live): a ``content`` list with one ``text``
block holding the JSON, ``stop_reason`` and ``usage``. Served behind the real ``SafeHttpClient``
with a fake resolver and ``httpx.MockTransport`` — CI never calls the provider.

Each test queues what the next calls answer: a JSON object (a valid answer), ``"not_json"``,
``"refusal"``, ``"max_tokens"``, an HTTP status (``429``, ``529``, ``401``, …) or
``"timeout"``. Every request is kept, so tests can check the headers and the body.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from app.domains.ai.anthropic import AnthropicAdapter
from app.providers.http.client import OutboundPolicy, SafeHttpClient
from pydantic import SecretStr

PUBLIC_IP = "160.79.104.10"
TEST_KEY = "sk-ant-test-not-a-real-key"
MODEL = "claude-sonnet-5-5"
POLICY = OutboundPolicy(
    connect_timeout=1, read_timeout=1, max_response_bytes=5_000_000, max_redirects=0
)


@dataclass
class AiSim:
    answers: list[Any] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)
    usage: tuple[int, int] = (1200, 300)  # input, output tokens per answer

    def queue(self, *answers: Any) -> AiSim:
        self.answers.extend(answers)
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method != "POST" or request.url.path != "/v1/messages":
            return httpx.Response(404, json={"type": "error"})
        if request.headers.get("x-api-key") != TEST_KEY:
            return httpx.Response(401, json={"type": "error", "error": {"type": "auth"}})
        if request.headers.get("anthropic-version") != "2023-06-01":
            return httpx.Response(400, json={"type": "error"})
        body = json.loads(request.content)
        fmt = body.get("output_config", {}).get("format", {})
        if fmt.get("type") != "json_schema" or "schema" not in fmt or "tools" in body:
            return httpx.Response(400, json={"type": "error"})
        if not self.answers:
            return httpx.Response(500, json={"type": "error"})
        answer = self.answers.pop(0)
        if answer == "timeout":
            raise httpx.ReadTimeout("simulated", request=request)
        if isinstance(answer, int):
            return httpx.Response(answer, json={"type": "error", "error": {"type": "sim"}})
        stop, text = "end_turn", ""
        if answer == "refusal":
            stop = "refusal"
        elif answer == "max_tokens":
            stop, text = "max_tokens", '{"cut": '
        elif answer == "not_json":
            text = "Here is your strategy: spend more."
        else:
            text = json.dumps(answer)
        tokens_in, tokens_out = self.usage
        return httpx.Response(
            200,
            json={
                "id": "msg_sim",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [{"type": "text", "text": text}],
                "stop_reason": stop,
                "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
            },
        )

    def http_factory(self) -> SafeHttpClient:
        return SafeHttpClient(
            POLICY,
            resolver=lambda host, port: [PUBLIC_IP],
            transport=httpx.MockTransport(self.handler),
        )

    def adapter(self, key: str | None = TEST_KEY) -> AnthropicAdapter:
        return AnthropicAdapter(SecretStr(key) if key else None, MODEL, self.http_factory)

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]
