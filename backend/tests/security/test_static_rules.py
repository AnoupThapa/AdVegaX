"""Source-level guards for rules that must hold across the codebase."""

from __future__ import annotations

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[2] / "app"


def _sources():
    for path in APP.rglob("*.py"):
        yield path, path.read_text(encoding="utf-8")


def test_no_session_level_tenant_settings():
    pattern = re.compile(
        r"(set_config\([^)]*,\s*false\))|(\bSET\s+(SESSION\s+)?app\.)", re.IGNORECASE
    )
    offenders = [str(p) for p, src in _sources() if pattern.search(src)]
    assert offenders == []


def test_security_durations_only_in_settings():
    """Session/token lifetimes are configurable settings, never literals (A15)."""
    offenders = []
    for path, src in _sources():
        # settings.py defines the values; humanize() only formats durations for email copy.
        if path.name == "settings.py" or path.as_posix().endswith("notifications/service.py"):
            continue
        if re.search(r"timedelta\(", src) or re.search(r"\b24\s*\*\s*60\b|\b86400\b", src):
            offenders.append(str(path))
    assert offenders == []


def test_no_http_clients_outside_providers():
    pattern = re.compile(
        r"^\s*(import|from)\s+(httpx|requests|aiohttp|urllib\.request|http\.client)\b", re.MULTILINE
    )
    offenders = [
        str(p) for p, src in _sources() if pattern.search(src) and "providers" not in p.parts
    ]
    assert offenders == []


def test_no_security_definer_functions():
    migrations = APP.parent / "alembic" / "versions"
    for path in migrations.glob("*.py"):
        assert "SECURITY DEFINER" not in path.read_text(encoding="utf-8").upper(), path
