"""Meta Graph answers → AdVegaX's platform-neutral records (Phase 4).

Meta sends ids as strings, money as decimal strings in the account currency (insights) or in
the currency's smallest unit (budgets, with the currency offset), and statuses as names or
numbers. Anything AdVegaX cannot read is skipped (and counted by the caller), never guessed.
Field formats are to be confirmed live (Step 0 item 1).
"""

from __future__ import annotations

import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.providers.base.types import ResourceDescriptor, ResourceKind

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
