"""Meta Graph answers → AdVegaX's platform-neutral records (Phase 4).

Meta sends ids as strings, money as decimal strings in the account currency (insights) or in
the currency's smallest unit (budgets, with the currency offset), and statuses as names or
numbers. Anything AdVegaX cannot read is skipped (and counted by the caller), never guessed.
Field formats are to be confirmed live (Step 0 item 1).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.providers.base.types import (
    AdBudgetRecord,
    AdCampaignRecord,
    AdEntityStatus,
    AdGroupRecord,
    AdLevel,
    AdPerformanceRecord,
    AdRecord,
    ResourceDescriptor,
    ResourceKind,
)

_ACCOUNT_ID = re.compile(r"^act_[0-9]{1,25}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")

# ``account_status`` (ad account reference; to confirm live) → AdVegaX platform status and,
# when the account cannot be used, the plain reason shown before linking.
ACCOUNT_STATUSES: dict[int, tuple[str, str | None]] = {
    1: ("active", None),  # ACTIVE
    9: ("active", None),  # IN_GRACE_PERIOD: still delivering
    201: ("active", None),  # ANY_ACTIVE
    2: ("suspended", "account_not_enabled"),  # DISABLED
    3: ("not_enabled", "account_unsettled"),  # UNSETTLED: an unpaid balance
    8: ("not_enabled", "account_unsettled"),  # PENDING_SETTLEMENT
    7: ("not_enabled", "account_under_review"),  # PENDING_RISK_REVIEW
    100: ("closed", "account_not_enabled"),  # PENDING_CLOSURE
    101: ("closed", "account_not_enabled"),  # CLOSED
    202: ("closed", "account_not_enabled"),  # ANY_CLOSED
}
UNKNOWN_STATUS = ("closed", "account_not_enabled")  # an unknown status is never treated as usable


def text(value: Any, limit: int = 255) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def zone(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return value


def currency(value: Any) -> str | None:
    return value if isinstance(value, str) and _CURRENCY.fullmatch(value) else None


def account_id(value: Any) -> str | None:
    return value if isinstance(value, str) and _ACCOUNT_ID.fullmatch(value) else None


def account_status(value: Any) -> tuple[str, str | None]:
    if isinstance(value, bool) or not isinstance(value, int):
        return UNKNOWN_STATUS
    return ACCOUNT_STATUSES.get(value, UNKNOWN_STATUS)


def business_name(row: dict[str, Any]) -> str | None:
    business = row.get("business")
    return text(business.get("name"), 512) if isinstance(business, dict) else None


def ad_account(row: dict[str, Any]) -> ResourceDescriptor | None:
    """One ``me/adaccounts`` row → a linkable (or explained) ad account resource."""
    found = account_id(row.get("id"))
    if found is None:
        return None
    money, tz = currency(row.get("currency")), zone(row.get("timezone_name"))
    _, reason = account_status(row.get("account_status"))
    if reason is None and (money is None or tz is None):
        reason = "account_details_missing"
    return ResourceDescriptor(
        kind=ResourceKind.AD_ACCOUNT,
        external_id=found,
        display_name=text(row.get("name")),
        currency=money,
        timezone=tz,
        unavailable_reason=reason,
        group_path=business_name(row),
    )


# ------------------------------------------------------------------ structure (4-04)
_OBJECT_ID = re.compile(r"^[0-9]{1,25}$")
_ENUM = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MINOR_UNITS = re.compile(r"^[0-9]{1,18}$")

# Currencies Meta counts in whole units (offset 1); every other currency is in cents (100).
# "Currencies and offsets" reference; to confirm live (Step 0 item 6).
OFFSET_ONE = frozenset(
    {"CLP", "COP", "CRC", "HUF", "ISK", "IDR", "JPY", "KRW", "PYG", "TWD", "VND"}
)

# Every ``effective_status`` value: lists hide archived and deleted objects unless asked.
EFFECTIVE_STATUSES: tuple[str, ...] = (
    # (This comment keeps the web app's error-code scan from reading the values as codes.)
    "ACTIVE",
    "PAUSED",
    "DELETED",
    "ARCHIVED",
    "PENDING_REVIEW",
    "DISAPPROVED",
    "PREAPPROVED",
    "PENDING_BILLING_INFO",
    "CAMPAIGN_PAUSED",
    "ADSET_PAUSED",
    "IN_PROCESS",
    "WITH_ISSUES",
)
# The status shown. ``effective_status`` already carries a parent's pause, archive or delete
# down to its children; review and billing states are delivery details of an active object.
_SHOWN = {
    "ACTIVE": AdEntityStatus.ACTIVE,
    "PAUSED": AdEntityStatus.PAUSED,
    "CAMPAIGN_PAUSED": AdEntityStatus.PAUSED,
    "ADSET_PAUSED": AdEntityStatus.PAUSED,
    "ARCHIVED": AdEntityStatus.ARCHIVED,
    "DELETED": AdEntityStatus.REMOVED,
}
_CONFIGURED = {
    "ACTIVE": AdEntityStatus.ACTIVE,
    "PAUSED": AdEntityStatus.PAUSED,
    "ARCHIVED": AdEntityStatus.ARCHIVED,
    "DELETED": AdEntityStatus.REMOVED,
}


def offset(currency_code: str) -> int:
    return 1 if currency_code in OFFSET_ONE else 100


def object_id(value: Any) -> str | None:
    return value if isinstance(value, str) and _OBJECT_ID.fullmatch(value) else None


def enum(value: Any) -> str | None:
    return value if isinstance(value, str) and _ENUM.fullmatch(value) else None


def status(row: dict[str, Any]) -> tuple[AdEntityStatus, str | None] | None:
    """The shown status and, when it differs, Meta's delivery status (display only)."""
    effective, configured = enum(row.get("effective_status")), enum(row.get("status"))
    shown = _SHOWN.get(effective or "") or _CONFIGURED.get(configured or "")
    if shown is None:
        return None
    detail = effective if effective and effective not in _SHOWN else None
    return shown, detail


def configured_status(row: dict[str, Any]) -> AdEntityStatus | None:
    """The object's own setting (``status``), not its delivery: what a change sets (10A)."""
    return _CONFIGURED.get(enum(row.get("status")) or "")


def money(value: Any, currency_code: str) -> Decimal | None:
    """A budget in the currency's smallest unit → an exact amount; "0" or none → None."""
    if isinstance(value, bool):
        return None
    raw = str(value) if isinstance(value, int) else value
    if not isinstance(raw, str) or not _MINOR_UNITS.fullmatch(raw):
        return None
    try:
        units = Decimal(raw)
    except InvalidOperation:  # pragma: no cover - the pattern allows digits only
        return None
    if units == 0:
        return None
    return units / offset(currency_code)


def day(value: Any) -> date | None:
    """``2026-03-01T00:00:00+0100`` → the date as Meta wrote it (the account's time zone)."""
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").date()
    except ValueError:
        return None


def budget(row: dict[str, Any], level: str, currency_code: str) -> AdBudgetRecord | None:
    """The object's own budget (daily or lifetime). Meta has no shared budgets: the budget
    belongs to the campaign (Advantage campaign budget) or to each ad set."""
    found = object_id(row.get("id"))
    if found is None:
        return None
    for period in ("daily", "lifetime"):
        amount = money(row.get(f"{period}_budget"), currency_code)
        if amount is not None:
            prefix = "campaign" if level == "campaign" else "adset"
            return AdBudgetRecord(
                external_id=f"{prefix}:{found}", level=level, period=period, amount=amount
            )
    return None


def _extensions(**values: Any) -> dict[str, Any] | None:
    kept = {k: v for k, v in values.items() if v is not None}
    return kept or None


def campaign(row: dict[str, Any], budget_id: str | None) -> AdCampaignRecord | None:
    found, shown = object_id(row.get("id")), status(row)
    name = text(row.get("name"))
    if found is None or shown is None or name is None:
        return None
    return AdCampaignRecord(
        external_id=found,
        name=name,
        status=shown[0],
        platform_type=enum(row.get("objective")),
        bidding_strategy_type=enum(row.get("bid_strategy")),
        start_date=day(row.get("start_time")),
        end_date=day(row.get("stop_time")),
        budget_external_id=budget_id,
        extensions=_extensions(buying_type=enum(row.get("buying_type")), delivery=shown[1]),
    )


def ad_set(row: dict[str, Any], budget_id: str | None) -> AdGroupRecord | None:
    found, parent, shown = object_id(row.get("id")), object_id(row.get("campaign_id")), status(row)
    name = text(row.get("name"))
    if found is None or parent is None or shown is None or name is None:
        return None
    return AdGroupRecord(
        external_id=found,
        campaign_external_id=parent,
        name=name,
        status=shown[0],
        platform_type=enum(row.get("optimization_goal")),
        budget_external_id=budget_id,
        extensions=_extensions(bid_strategy=enum(row.get("bid_strategy")), delivery=shown[1]),
    )


def ad(row: dict[str, Any]) -> AdRecord | None:
    found, parent, shown = object_id(row.get("id")), object_id(row.get("adset_id")), status(row)
    if found is None or parent is None or shown is None:
        return None
    creative = row.get("creative")
    if not isinstance(creative, dict):
        creative = {}
    return AdRecord(
        external_id=found,
        ad_group_external_id=parent,
        status=shown[0],
        name=text(row.get("name")),
        extensions=_extensions(
            creative_id=object_id(creative.get("id")),
            creative_name=text(creative.get("name")),
            delivery=shown[1],
        ),
    )


# ------------------------------------------------------------------ daily figures (4-05)
PURCHASE = "omni_purchase"  # website, app and offline purchases combined, as Ads Manager (Q-4-5)
# Meta's own funnel actions (Phase 7, Q-7-4), cross-channel like ``omni_purchase`` where Meta
# offers it. Names as documented; Step 0 (7-01) confirms them live.
LANDING_PAGE_VIEW = "landing_page_view"
CONTENT_VIEW = "omni_view_content"
ADD_TO_CART = "omni_add_to_cart"
CHECKOUT = "omni_initiated_checkout"
_COUNT = re.compile(r"^[0-9]{1,15}$")
_AMOUNT = re.compile(r"^[0-9]{1,15}(?:\.[0-9]{1,6})?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_UNSET = object()


def count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    return int(value) if isinstance(value, str) and _COUNT.fullmatch(value) else None


def amount(value: Any) -> Decimal | None:
    """An exact amount as Meta writes it (``"12.34"``, already in the currency's units)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value) if value >= 0 else None
    return Decimal(value) if isinstance(value, str) and _AMOUNT.fullmatch(value) else None


def iso_day(value: Any) -> date | None:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def action(rows: Any, action_type: str) -> Decimal | None:
    """The value of one action type in Meta's ``actions`` / ``action_values`` list. No list,
    or the type absent, means Meta recorded none: a real 0. An unreadable entry → None."""
    if rows is None:
        return Decimal(0)
    if not isinstance(rows, list):
        return None
    found: Any = _UNSET
    for entry in rows:
        if isinstance(entry, dict) and entry.get("action_type") == action_type:
            if found is not _UNSET:
                return None  # listed twice: never summed or guessed
            found = entry.get("value")
    return Decimal(0) if found is _UNSET else amount(found)


def performance(row: dict[str, Any], level: AdLevel) -> AdPerformanceRecord | None:
    """One day of one entity. None for a row that cannot be read (counted by the caller)."""
    first, last = iso_day(row.get("date_start")), iso_day(row.get("date_stop"))
    if first is None or first != last:
        return None
    campaign_id, group_id = object_id(row.get("campaign_id")), object_id(row.get("adset_id"))
    entity: str | None
    if level is AdLevel.ACCOUNT:
        entity = None
    elif level is AdLevel.CAMPAIGN:
        entity = campaign_id
    elif level is AdLevel.AD_GROUP:
        entity = group_id
    else:
        entity = object_id(row.get("ad_id"))
    if level is not AdLevel.ACCOUNT and entity is None:
        return None
    if level is AdLevel.AD and group_id is None:
        return None
    spend = amount(row.get("spend")) if row.get("spend") is not None else Decimal(0)
    impressions = count(row.get("impressions", 0))
    clicks = count(row.get("inline_link_clicks", 0))
    purchases = action(row.get("actions"), PURCHASE)
    value = action(row.get("action_values"), PURCHASE)
    if None in (spend, impressions, clicks, purchases, value):
        return None
    return AdPerformanceRecord(
        level=level,
        day=first,
        entity_external_id=entity,
        campaign_external_id=campaign_id if level in (AdLevel.AD_GROUP, AdLevel.AD) else None,
        ad_group_external_id=group_id if level is AdLevel.AD else None,
        impressions=impressions,
        clicks=clicks,
        cost=spend,
        conversions=purchases,
        conversion_value=value,
        # An unreadable funnel action leaves only that figure unknown; the row is kept.
        landing_page_views=action(row.get("actions"), LANDING_PAGE_VIEW),
        content_views=action(row.get("actions"), CONTENT_VIEW),
        adds_to_cart=action(row.get("actions"), ADD_TO_CART),
        checkouts_initiated=action(row.get("actions"), CHECKOUT),
    )
