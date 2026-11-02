"""The desktop install runs the backend on Windows; some Python formatting only works elsewhere."""

import re
from datetime import UTC, datetime
from pathlib import Path

from app.domains.billing.service import _day

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [*(ROOT / "app").rglob("*.py"), *(ROOT / "demo").rglob("*.py")]

# strftime codes that Windows rejects with "ValueError: Invalid format string":
# "%-d", "%-m", "%-H" … (GNU: no padding) and "%e", "%k", "%l", "%P", "%s" (GNU-only).
GNU_ONLY = re.compile(r"%-[a-zA-Z]|%[ekPsl](?![a-zA-Z])")


def test_no_source_uses_a_format_code_that_windows_rejects() -> None:
    assert SOURCES, "no sources found"
    found = [
        f"{path.relative_to(ROOT)}:{number}: {line.strip()}"
        for path in SOURCES
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "strftime" in line and GNU_ONLY.search(line)
    ]
    assert found == []


def test_billing_email_day_has_no_leading_zero_and_survives_empty() -> None:
    assert _day(datetime(2027, 1, 7, tzinfo=UTC)) == "7 January 2027"
    assert _day(datetime(2027, 11, 21, tzinfo=UTC)) == "21 November 2027"
    assert _day(None) == ""
