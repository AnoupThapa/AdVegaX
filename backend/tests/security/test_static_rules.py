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
ADVERTISING_PROVIDER_DIRS = ("google_ads", "meta_ads")
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


# Phase 4 (PHASE_04_PLAN §3, §7, acceptance criterion 4): the Meta provider sends every request
# through one guarded ``_send`` (GET, plus the token exchange, insights reports and removing
# AdVegaX's own permission) and never asks for ``ads_management``.
def test_meta_requests_all_pass_the_read_only_guard():
    folder = APP / "providers" / "meta_ads"
    sources = {p.name: p.read_text(encoding="utf-8") for p in folder.rglob("*.py")}
    calls = {name: src.count(".request(") for name, src in sources.items() if ".request(" in src}
    assert calls == {"client.py": 1}
    client = sources["client.py"]
    send = client[client.index("    def _send(") :]
    send = send[: send.index("\n    def ", 10)]
    assert "_allowed(method, path)" in send and send.index("_allowed(") < send.index(".request(")


def test_meta_never_asks_for_write_permissions():
    for path in (APP / "providers" / "meta_ads").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert "ads_management" not in src, path.name
        assert "pages_manage" not in src, path.name


# ------------------------------------------------------------------ analytics is read-only
# Phase 5 (PHASE_05_PLAN §3, §7, acceptance criterion 4): analytics providers may only read.
# GA4 methods are written as ``…/properties/{id}:runReport``; every ``:verb`` an analytics
# provider names must be a report read. Property discovery is plain GET (``accountSummaries``,
# ``properties/{id}``). ``analytics.edit`` and the full ``analytics`` permission are never
# requested, and no request uses PATCH, PUT or DELETE.
ANALYTICS_PROVIDER_DIRS = ("google_analytics",)
ALLOWED_ANALYTICS_METHODS = {"runReport", "batchRunReports"}
_ANALYTICS_METHOD = re.compile(r"""[\w}"']:([a-zA-Z]+)\b""")
_ANALYTICS_WRITES = re.compile(
    r"""analytics\.edit|auth/analytics["']|\b(PATCH|PUT|DELETE)\b|:(create|update|delete|"""
    r"""archive|acknowledge|provision)""",
)


def analytics_write_calls(source: str) -> list[str]:
    """Every platform call in ``source`` that is not an allowed read."""
    found = []
    for line in source.splitlines():
        code = line.split("#", 1)[0]
        if _ANALYTICS_WRITES.search(code):
            found.append(code.strip())
            continue
        if "properties" not in code and "accountSummaries" not in code:
            continue
        for verb in _ANALYTICS_METHOD.findall(code):
            if verb not in ALLOWED_ANALYTICS_METHODS and verb not in {"https", "http"}:
                found.append(code.strip())
    return found


def test_the_analytics_read_only_check_catches_write_calls():
    assert analytics_write_calls('URL = f"/v1beta/properties/{pid}:runReport"') == []
    assert analytics_write_calls('f"{DATA}/v1beta/properties/{pid}:batchRunReports"') == []
    assert analytics_write_calls('ADMIN = "https://analyticsadmin.googleapis.com/v1beta"') == []
    assert analytics_write_calls('path = f"/v1beta/accountSummaries"') == []
    assert (
        analytics_write_calls('SCOPE = "https://www.googleapis.com/auth/analytics.readonly"') == []
    )
    for bad in (
        'f"/v1beta/properties/{pid}:runAccessReport"',
        'f"/v1beta/properties/{pid}/keyEvents:create"',
        'f"/v1beta/properties/{pid}:acknowledgeUserDataCollection"',
        'f"/v1alpha/accounts:provisionAccountTicket"',
        'client.request("PATCH", f"/v1beta/properties/{pid}")',
        'client.request("DELETE", url)',
        'SCOPE = "https://www.googleapis.com/auth/analytics.edit"',
        'SCOPE = "https://www.googleapis.com/auth/analytics"',
    ):
        assert analytics_write_calls(bad), bad


def test_analytics_providers_only_read():
    offenders = {}
    for name in ANALYTICS_PROVIDER_DIRS:
        folder = APP / "providers" / name
        for path in folder.rglob("*.py") if folder.exists() else ():
            calls = analytics_write_calls(path.read_text(encoding="utf-8"))
            if calls:
                offenders[path.relative_to(APP).as_posix()] = calls
    assert offenders == {}


def test_analytics_providers_declare_no_write_capability():
    from app.providers.base.capabilities import Capability

    writes = {Capability.CREATE_CAMPAIGN, Capability.VALIDATE_ONLY}
    for path in (APP / "providers").rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel.split("/")[1] in ANALYTICS_PROVIDER_DIRS:
            src = path.read_text(encoding="utf-8")
            assert not any(f"Capability.{c.name}" in src for c in writes), rel
