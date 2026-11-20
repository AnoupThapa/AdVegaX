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
from datetime import date
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.providers.base.types import (
    AnalyticsBreakdown,
    AnalyticsDailyRecord,
    AnalyticsPropertyState,
    AnalyticsQuality,
    ResourceDescriptor,
    ResourceKind,
)

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


# ------------------------------------------------------------------ daily reports (5-05)
# Data API ``v1beta`` report shape (checked 2026-10-19; to confirm live, Step 0 item 2):
# ``{"dimensionHeaders": [{"name"}], "metricHeaders": [{"name", "type"}], "rows":
# [{"dimensionValues": [{"value"}], "metricValues": [{"value"}]}], "rowCount", "metadata":
# {"dataLossFromOtherRow", "subjectToThresholding", "samplingMetadatas",
# "dataTruncationReasons", "currencyCode", "timeZone"}}``. Values are strings; ``date`` is
# ``YYYYMMDD`` in the property's time zone; money is in the property's currency.
PAGE_ROWS = 10_000  # Google's default page; up to 250,000 is allowed
OTHER = "(other)"
NOT_SET = "(not set)"
METRICS = (
    "sessions",
    "engagedSessions",
    "totalUsers",
    "newUsers",
    "keyEvents",
    "ecommercePurchases",
    "purchaseRevenue",
    # The funnel's middle (Phase 7, Q-7-3): event-scoped, so compatible with every view.
    # Ten metrics is the Data API's limit per report.
    "itemViewEvents",
    "addToCarts",
    "checkouts",
)
VIEW_DIMENSIONS: dict[AnalyticsBreakdown, tuple[str, ...]] = {
    AnalyticsBreakdown.TOTAL: ("date",),
    AnalyticsBreakdown.CHANNEL: ("date", "sessionDefaultChannelGroup"),
    AnalyticsBreakdown.SOURCE: ("date", "sessionSource", "sessionMedium", "sessionCampaignName"),
    # The path a session started on, without its query string (no personal data in URLs).
    AnalyticsBreakdown.LANDING_PAGE: ("date", "landingPage"),
}
_INT = re.compile(r"^[0-9]{1,18}$")
_DECIMAL = re.compile(r"^-?[0-9]{1,14}(\.[0-9]{1,12})?$")
_DATE = re.compile(r"^([0-9]{4})([0-9]{2})([0-9]{2})$")


def report_request(
    view: AnalyticsBreakdown, first: date, last: date, *, offset: int = 0
) -> dict[str, Any]:
    """One view of one date range, ordered by every dimension so pages never overlap."""
    names = VIEW_DIMENSIONS[view]
    request: dict[str, Any] = {
        "dateRanges": [{"startDate": first.isoformat(), "endDate": last.isoformat()}],
        "dimensions": [{"name": n} for n in names],
        "metrics": [{"name": m} for m in METRICS],
        "orderBys": [{"dimension": {"dimensionName": n}} for n in names],
        "limit": str(PAGE_ROWS),
    }
    if offset:
        request["offset"] = str(offset)
    return request


def _count(value: Any) -> int | None:
    return int(value) if isinstance(value, str) and _INT.fullmatch(value) else None


def _amount(value: Any, *, negative: bool = False) -> Decimal | None:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        return None
    amount = Decimal(value)
    return amount if negative or amount >= 0 else None


def _day(value: Any) -> date | None:
    found = _DATE.fullmatch(value) if isinstance(value, str) else None
    if found is None:
        return None
    try:
        return date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
    except ValueError:
        return None


def _path(value: str) -> str:
    """A landing page as a path only: anything after ``?`` or ``#`` is dropped, in case a
    property reports it (a query string can hold personal data)."""
    return value.split("?", 1)[0].split("#", 1)[0] or NOT_SET


def _label(value: Any) -> str:
    return text(value) or NOT_SET  # GA4 says "(not set)" itself; an empty value means the same


@dataclass
class ParsedReport:
    """One page of one view: the rows read, how many Google has in all, what it said."""

    records: list[AnalyticsDailyRecord]
    row_count: int
    rows_seen: int
    quality: AnalyticsQuality
    skipped: int = 0


def quality_of(report: dict[str, Any]) -> AnalyticsQuality:
    meta = report.get("metadata")
    meta = meta if isinstance(meta, dict) else {}
    return AnalyticsQuality(
        other_row=meta.get("dataLossFromOtherRow") is True,
        thresholded=meta.get("subjectToThresholding") is True,
        sampled=bool(meta.get("samplingMetadatas")),
        truncated=bool(meta.get("dataTruncationReasons")),
    )


def merge_quality(a: AnalyticsQuality, b: AnalyticsQuality) -> AnalyticsQuality:
    return AnalyticsQuality(
        other_row=a.other_row or b.other_row,
        thresholded=a.thresholded or b.thresholded,
        sampled=a.sampled or b.sampled,
        truncated=a.truncated or b.truncated,
    )


def _headers(report: dict[str, Any], key: str) -> list[str] | None:
    found = report.get(key)
    if not isinstance(found, list):
        return None
    names = [h.get("name") if isinstance(h, dict) else None for h in found]
    return (
        [n for n in names if isinstance(n, str)] if all(isinstance(n, str) for n in names) else None
    )


def parse_report(
    view: AnalyticsBreakdown, report: dict[str, Any], first: date, last: date
) -> ParsedReport | None:
    """A report page → records; None when its headers are not the ones asked for (the caller
    treats that as an unexpected answer). Rows outside the range, without a readable day or
    with a value count that does not match the headers are skipped and counted."""
    rows = report.get("rows") or []
    count = report.get("rowCount", 0)
    if not isinstance(rows, list) or isinstance(count, bool) or not isinstance(count, int):
        return None
    quality = quality_of(report)
    if not rows:  # Google leaves the headers out of an empty report
        return ParsedReport([], max(0, count), 0, quality)
    dims, mets = _headers(report, "dimensionHeaders"), _headers(report, "metricHeaders")
    if dims != list(VIEW_DIMENSIONS[view]) or mets is None or set(mets) != set(METRICS):
        return None
    records: list[AnalyticsDailyRecord] = []
    skipped = 0
    for row in rows:
        values = _values(row, "dimensionValues", len(dims))
        measures = _values(row, "metricValues", len(mets))
        day = _day(values[0]) if values else None
        if values is None or measures is None or day is None or not first <= day <= last:
            skipped += 1
            continue
        m = dict(zip(mets, measures, strict=True))
        labels = [_label(v) for v in values[1:]]
        records.append(
            AnalyticsDailyRecord(
                breakdown=view,
                day=day,
                channel_group=labels[0] if view is AnalyticsBreakdown.CHANNEL else None,
                source=labels[0] if view is AnalyticsBreakdown.SOURCE else None,
                medium=labels[1] if view is AnalyticsBreakdown.SOURCE else None,
                campaign=labels[2] if view is AnalyticsBreakdown.SOURCE else None,
                landing_page=_path(labels[0]) if view is AnalyticsBreakdown.LANDING_PAGE else None,
                sessions=_count(m["sessions"]),
                engaged_sessions=_count(m["engagedSessions"]),
                total_users=_count(m["totalUsers"]),
                new_users=_count(m["newUsers"]),
                key_events=_amount(m["keyEvents"]),
                purchases=_count(m["ecommercePurchases"]),
                # Purchases minus refunds: a day with more refunds is negative (0015).
                purchase_revenue=_amount(m["purchaseRevenue"], negative=True),
                item_view_events=_count(m["itemViewEvents"]),
                add_to_carts=_count(m["addToCarts"]),
                checkouts=_count(m["checkouts"]),
                quality=AnalyticsQuality(
                    other_row=quality.other_row or OTHER in labels,
                    thresholded=quality.thresholded,
                    sampled=quality.sampled,
                    truncated=quality.truncated,
                ),
            )
        )
    return ParsedReport(records, max(count, 0), len(rows), quality, skipped)


def _values(row: Any, key: str, expected: int) -> list[Any] | None:
    found = row.get(key) if isinstance(row, dict) else None
    if not isinstance(found, list) or len(found) != expected:
        return None
    return [v.get("value") if isinstance(v, dict) else None for v in found]
