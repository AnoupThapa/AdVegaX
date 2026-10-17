"""Google Ads report rows → AdVegaX's platform-neutral advertising records (Phase 3).

Rows arrive as Google's REST JSON: camelCase keys, int64 values as strings, money in
**micros** (millionths of the account currency), enums as names (to confirm in Step 0 item 1).
Money becomes an exact ``Decimal``; nothing is rounded here. A row that cannot be read is
skipped (and counted by the caller) rather than guessed.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.providers.base.types import (
    AdBudgetRecord,
    AdCampaignRecord,
    AdEntityStatus,
    AdGroupRecord,
    AdRecord,
)

MICROS = Decimal(1_000_000)
DAILY_PERIODS = frozenset({"DAILY", "FIXED_DAILY"})
_ID = re.compile(r"^[0-9]{1,20}$")
_STATUSES = {
    "ENABLED": AdEntityStatus.ACTIVE,
    "PAUSED": AdEntityStatus.PAUSED,
    "REMOVED": AdEntityStatus.REMOVED,
}
# Google's account statuses → AdVegaX's platform statuses (Q-3-3).
ACCOUNT_STATUSES = {
    "ENABLED": "active",
    "CANCELED": "cancelled",
    "CANCELLED": "cancelled",
    "SUSPENDED": "suspended",
    "CLOSED": "closed",
}


def money(value: Any) -> Decimal | None:
    """Micros (an int64, usually sent as a string) → exact Decimal; None when absent."""
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number != number.to_integral_value():
        return None
    return number / MICROS


def ident(value: Any) -> str | None:
    text = str(value) if value is not None else ""
    return text if _ID.fullmatch(text) else None


def resource_id(value: Any) -> str | None:
    """The last part of a resource name, e.g. ``customers/1/campaigns/22`` → ``22``."""
    if not isinstance(value, str) or "/" not in value:
        return None
    return ident(value.rsplit("/", 1)[-1])


def status(value: Any) -> AdEntityStatus | None:
    return _STATUSES.get(str(value)) if value is not None else None


def text(value: Any, limit: int = 512) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def day(value: Any) -> date | None:
    """``"2026-10-01"`` or ``"2026-10-01 00:00:00"`` → the date (account time zone)."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def budget(row: dict[str, Any]) -> AdBudgetRecord | None:
    data = row.get("campaignBudget")
    if not isinstance(data, dict) or (budget_id := ident(data.get("id"))) is None:
        return None
    period = str(data.get("period", ""))
    if period == "CUSTOM_PERIOD":  # a total for the campaign's run
        return AdBudgetRecord(
            external_id=budget_id,
            level="campaign",
            period="lifetime",
            amount=money(data.get("totalAmountMicros")),
            shared=data.get("explicitlyShared") is True,
            name=text(data.get("name")),
        )
    if period not in DAILY_PERIODS:
        return None
    return AdBudgetRecord(
        external_id=budget_id,
        level="campaign",
        period="daily",
        amount=money(data.get("amountMicros")),
        shared=data.get("explicitlyShared") is True,
        name=text(data.get("name")),
    )


def campaign(row: dict[str, Any]) -> AdCampaignRecord | None:
    data = row.get("campaign")
    if not isinstance(data, dict):
        return None
    campaign_id, name, state = (
        ident(data.get("id")),
        text(data.get("name")),
        status(data.get("status")),
    )
    if campaign_id is None or name is None or state is None:
        return None
    start, end = day(data.get("startDateTime")), day(data.get("endDateTime"))
    if start is not None and end is not None and end < start:
        end = None
    return AdCampaignRecord(
        external_id=campaign_id,
        name=name,
        status=state,
        platform_type=text(data.get("advertisingChannelType"), 64),
        bidding_strategy_type=text(data.get("biddingStrategyType"), 64),
        start_date=start,
        end_date=end,
        budget_external_id=resource_id(data.get("campaignBudget")),
    )


def ad_group(row: dict[str, Any]) -> AdGroupRecord | None:
    data = row.get("adGroup")
    if not isinstance(data, dict):
        return None
    group_id, campaign_id = ident(data.get("id")), resource_id(data.get("campaign"))
    name, state = text(data.get("name")), status(data.get("status"))
    if group_id is None or campaign_id is None or name is None or state is None:
        return None
    return AdGroupRecord(
        external_id=group_id,
        campaign_external_id=campaign_id,
        name=name,
        status=state,
        platform_type=text(data.get("type"), 64),
    )


def ad(row: dict[str, Any]) -> AdRecord | None:
    data = row.get("adGroupAd")
    if not isinstance(data, dict):
        return None
    raw = data.get("ad")
    inner: dict[str, Any] = raw if isinstance(raw, dict) else {}
    ad_id, group_id = ident(inner.get("id")), resource_id(data.get("adGroup"))
    state = status(data.get("status"))
    if ad_id is None or group_id is None or state is None:
        return None
    return AdRecord(
        external_id=ad_id,
        ad_group_external_id=group_id,
        status=state,
        name=text(inner.get("name")),
        platform_type=text(inner.get("type"), 64),
    )
