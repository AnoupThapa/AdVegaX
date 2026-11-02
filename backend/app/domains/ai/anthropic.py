"""Anthropic's Claude API as a model adapter (Phase 8, task 8-02, PLAN Q-8-1, §4.1; A26).

``POST https://api.anthropic.com/v1/messages`` (``anthropic-version: 2023-06-01``) with
**structured outputs** — ``output_config.format = {"type": "json_schema", "schema": …}`` — so the
answer is constrained to AdVegaX's schema (checked 2026-10-25; Step 0 confirms it live). The
JSON arrives as the text of the answer's ``text`` block; ``stop_reason`` ``refusal`` or
``max_tokens`` means the text may not follow the schema. Usage (``input_tokens``,
``output_tokens``) is read for the cost estimate.

One fixed address, through the SSRF-safe client; the key travels only in the ``x-api-key``
header and is never logged (the client masks it). No tools are offered to the model.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import SecretStr

from app.domains.ai.adapter import (
    AiError,
    AiNotConfigured,
    AiTimedOut,
    AiUnavailable,
    ModelAnswer,
    ModelRequest,
)
from app.providers.base.errors import OutboundTimeoutError, ProviderError
from app.providers.http.client import SafeHttpClient

HOST = "api.anthropic.com"
PATH = "/v1/messages"
API_VERSION = "2023-06-01"
HttpFactory = Callable[[], SafeHttpClient]


def _tokens(usage: Any, key: str) -> int:
    value = usage.get(key) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and value >= 0 else 0


class AnthropicAdapter:
    provider = "anthropic"

    def __init__(self, api_key: SecretStr | None, model: str, http_factory: HttpFactory) -> None:
        self._key = api_key
        self.model = model
        self._http = http_factory

    def generate(self, request: ModelRequest) -> ModelAnswer:
        if self._key is None or not self._key.get_secret_value():
            raise AiNotConfigured()
        body = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.prompt}],
            "output_config": {"format": {"type": "json_schema", "schema": request.schema}},
        }
        client = self._http()
        try:
            response = client.request(
                "POST",
                f"https://{HOST}{PATH}",
                headers={
                    "x-api-key": self._key.get_secret_value(),
                    "anthropic-version": API_VERSION,
                    "content-type": "application/json",
                },
                json=body,
                follow_redirects=False,
            )
        except OutboundTimeoutError as exc:
            raise AiTimedOut() from exc
        except ProviderError as exc:
            raise AiUnavailable() from exc
        finally:
            client.close()
        if response.status_code in (401, 403):
            raise AiNotConfigured("ai_key_refused")
        if response.status_code == 429 or response.status_code >= 500:
            raise AiUnavailable()  # rate limited, overloaded (529) or a provider error
        if response.status_code != 200:
            raise AiError("ai_request_refused")  # 400: AdVegaX sent something it should not
        try:
            answer = json.loads(response.content)
        except ValueError as exc:
            raise AiUnavailable("ai_unexpected_response") from exc
        if not isinstance(answer, dict):
            raise AiUnavailable("ai_unexpected_response")
        usage = answer.get("usage")
        tokens_in, tokens_out = _tokens(usage, "input_tokens"), _tokens(usage, "output_tokens")
        stop = answer.get("stop_reason")
        if stop == "refusal":
            return ModelAnswer(None, "refused", tokens_in, tokens_out)
        if stop == "max_tokens":
            return ModelAnswer(None, "too_long", tokens_in, tokens_out)
        blocks = answer.get("content")
        text = next(
            (
                b.get("text")
                for b in (blocks if isinstance(blocks, list) else [])
                if isinstance(b, dict) and b.get("type") == "text"
            ),
            None,
        )
        try:
            data = json.loads(text) if isinstance(text, str) else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return ModelAnswer(None, "not_json", tokens_in, tokens_out)
        return ModelAnswer(data, None, tokens_in, tokens_out)
