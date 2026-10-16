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
    """Only the credentials module touches encryption; only service and the token-lifecycle
    module decrypt (2A-04 moved job-time decryption into ``tokens.py``, which refreshes first)."""
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
        "domains/integrations/tokens.py",
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


# ------------------------------------------------------------------ advertising is read-only
# Phase 3 (PHASE_03_PLAN §3, §7, acceptance criterion 4): advertising providers may only read.
# Google Ads REST methods are written as ``…/customers/{id}/googleAds:search``; every ``:verb``
# a provider names must be one of these reads. Any change to an ad account goes only through
# the Action Engine (Phase 10A), which does not exist yet.
ADVERTISING_PROVIDER_DIRS = ("google_ads", "meta")
ALLOWED_AD_METHODS = {"listAccessibleCustomers", "search", "searchStream"}
_AD_METHOD = re.compile(r"""[\w}]:([a-zA-Z]+)\b""")
_AD_WRITE_WORDS = re.compile(r"mutate|:upload|:apply|:remove|:create|:update", re.IGNORECASE)


def advertising_write_calls(source: str) -> list[str]:
    """Every platform method in ``source`` that is not an allowed read."""
    found = []
    for line in source.splitlines():
        code = line.split("#", 1)[0]
        if _AD_WRITE_WORDS.search(code):
            found.append(code.strip())
            continue
        platform_path = "googleAds" in code or "customers" in code
        for verb in _AD_METHOD.findall(code):
            if verb not in ALLOWED_AD_METHODS and platform_path:
                found.append(code.strip())
    return found


def test_the_read_only_check_catches_write_calls():
    assert advertising_write_calls('URL = f"/customers/{cid}/googleAds:search"') == []
    assert advertising_write_calls('"/customers:listAccessibleCustomers"') == []
    assert advertising_write_calls('stream = f"{base}/googleAds:searchStream"') == []
    for bad in (
        'f"/customers/{cid}/campaigns:mutate"',
        'f"/customers/{cid}/googleAds:mutate"',
        'f"/customers/{cid}:uploadClickConversions"',
        'f"/customers/{cid}/campaignBudgets:mutate"',
        "MutateCampaignsRequest",
    ):
        assert advertising_write_calls(bad), bad


def test_advertising_providers_only_read():
    offenders = {}
    for name in ADVERTISING_PROVIDER_DIRS:
        folder = APP / "providers" / name
        for path in folder.rglob("*.py") if folder.exists() else ():
            calls = advertising_write_calls(path.read_text(encoding="utf-8"))
            if calls:
                offenders[path.relative_to(APP).as_posix()] = calls
    assert offenders == {}


def test_advertising_providers_declare_no_write_capability():
    from app.providers.base.capabilities import Capability

    writes = {Capability.CREATE_CAMPAIGN, Capability.VALIDATE_ONLY}
    for path in (APP / "providers").rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel.split("/")[1] in ADVERTISING_PROVIDER_DIRS:
            src = path.read_text(encoding="utf-8")
            assert not any(f"Capability.{c.name}" in src for c in writes), rel
