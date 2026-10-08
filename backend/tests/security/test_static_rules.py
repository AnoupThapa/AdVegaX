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
        literal = r"timedelta\(\s*(?:(?:weeks|days|hours|minutes|seconds)\s*=\s*)?\d"
        if re.search(literal, src) or re.search(r"\b24\s*\*\s*60\b|\b86400\b", src):
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


def test_credential_boundary():
    """Only the credentials module touches encryption; only service/jobs/rotation decrypt."""
    importers_of_encryption = {
        p.relative_to(APP).as_posix()
        for p, src in _sources()
        if re.search(r"from app\.core\.security\.encryption import", src)
    }
    assert importers_of_encryption <= {
        "core/settings.py",
        "runtime.py",
        "domains/integrations/credentials.py",
        "domains/integrations/rotation.py",
    }
    decrypters = {
        p.relative_to(APP).as_posix()
        for p, src in _sources()
        if re.search(r"\bload_secrets\b", src)
    }
    assert decrypters == {
        "domains/integrations/credentials.py",
        "domains/integrations/service.py",
        "domains/integrations/jobs.py",
    }


def test_core_domains_do_not_import_platform_specific_code():
    """D19: platform code lives in providers/<platform>; core imports only providers.base."""
    offenders = []
    for path, src in _sources():
        rel = path.relative_to(APP).as_posix()
        if rel.startswith(("providers/", "workers/")):
            continue
        if re.search(r"from app\.providers\.(?!base\b|http\.client\b|http\.ratelimit\b)", src):
            offenders.append(rel)
    assert offenders == []
