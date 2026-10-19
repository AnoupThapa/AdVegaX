"""Google Analytics answers → AdVegaX's platform-neutral records (Phase 5).

Admin API ``v1beta`` shapes (checked 2026-10-19; to confirm live, Step 0 item 1): an account
summary is ``{"account": "accounts/1", "displayName", "propertySummaries": [{"property":
"properties/2", "displayName", "propertyType"}]}``; a property carries ``currencyCode``,
``timeZone`` (IANA) and, when it is in the bin, ``deleteTime``. Anything AdVegaX cannot read
is skipped (and counted by the caller), never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.providers.base.types import AnalyticsPropertyState, ResourceDescriptor, ResourceKind

_PROPERTY = re.compile(r"^properties/([0-9]{1,20})$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


def text(value: Any, limit: int = 255) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def property_id(value: Any) -> str | None:
    """``properties/123`` → ``123`` (AdVegaX keeps the digits, as GA4 shows them)."""
    found = _PROPERTY.fullmatch(value) if isinstance(value, str) else None
    return found.group(1) if found else None


def currency(value: Any) -> str | None:
    return value if isinstance(value, str) and _CURRENCY.fullmatch(value) else None


def zone(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return value


@dataclass(frozen=True)
class Summary:
    """One property as listed in an account summary."""

    id: str
    name: str | None
    account_name: str | None


def summaries(row: dict[str, Any]) -> tuple[list[Summary], int]:
    """The properties of one account summary, and how many entries could not be read."""
    account_name = text(row.get("displayName"), 512)
    found, skipped = [], 0
    entries = row.get("propertySummaries") or []
    for entry in entries if isinstance(entries, list) else []:
        pid = property_id(entry.get("property")) if isinstance(entry, dict) else None
        if pid is None:
            skipped += 1
            continue
        found.append(Summary(pid, text(entry.get("displayName")), account_name))
    if not isinstance(entries, list):
        skipped += 1
    return found, skipped


def descriptor(
    summary: Summary, details: dict[str, Any] | None, reason: str | None
) -> ResourceDescriptor:
    """A linkable (or explained) property resource, grouped by its Analytics account."""
    money = currency(details.get("currencyCode")) if details else None
    tz = zone(details.get("timeZone")) if details else None
    if reason is None and details is not None and details.get("deleteTime"):
        reason = "property_deleted"
    if reason is None and (money is None or tz is None):
        reason = "property_details_missing"
    name = text(details.get("displayName")) if details else None
    return ResourceDescriptor(
        kind=ResourceKind.ANALYTICS_PROPERTY,
        external_id=summary.id,
        display_name=name or summary.name,
        currency=money,
        timezone=tz,
        unavailable_reason=reason,
        group_path=summary.account_name,
    )


def property_state(external_id: str, details: dict[str, Any]) -> AnalyticsPropertyState | None:
    """The property as GA4 reports it now; None when its id, currency or time zone cannot be
    read (the caller treats that as an unexpected answer)."""
    money, tz = currency(details.get("currencyCode")), zone(details.get("timeZone"))
    if property_id(details.get("name")) != external_id or money is None or tz is None:
        return None
    deleted = bool(details.get("deleteTime"))
    return AnalyticsPropertyState(
        external_id=external_id,
        name=text(details.get("displayName")),
        currency=money,
        timezone=tz,
        platform_status="deleted" if deleted else "active",
        unavailable_reason="property_deleted" if deleted else None,
    )
