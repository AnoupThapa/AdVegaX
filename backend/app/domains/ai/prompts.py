"""Versioned prompts (Phase 8, task 8-02, PLAN §3, exit criterion: every strategy traceable to
its prompt version).

A prompt is AdVegaX's fixed system text plus a task template. Its **hash** (SHA-256 of both)
is recorded with every run, so a changed text without a new version is visible. Prompts live in
code, reviewed like code; ``prompt_versions`` keeps one row per name and version used.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system: str
    template: str  # str.format fields, filled by the task (8-03 / 8-04)

    @property
    def template_hash(self) -> str:
        return hashlib.sha256(f"{self.system}\x00{self.template}".encode()).hexdigest()

    def render(self, **parts: str) -> str:
        return self.template.format(**parts)


REGISTRY: dict[tuple[str, str], Prompt] = {}


def register(prompt: Prompt) -> Prompt:
    key = (prompt.name, prompt.version)
    existing = REGISTRY.get(key)
    if existing is not None and existing.template_hash != prompt.template_hash:
        raise ValueError(f"prompt {prompt.name} {prompt.version} changed without a new version")
    REGISTRY[key] = prompt
    return prompt
