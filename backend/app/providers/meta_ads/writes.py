"""Meta campaign changes — the only Meta write calls (Phase 10A, task 10A-03).

PHASE_10A_PLAN §4.1 (Meta Marketing API, checked 2026-10-26; to confirm in Step 0):

* a campaign is changed by ``POST /<campaign id>`` with ``status`` (``ACTIVE`` / ``PAUSED``)
  or ``daily_budget`` in the account currency's **smallest unit** (cents for most currencies;
  whole units for the currencies Meta counts that way, ``mapping.OFFSET_ONE``);
* ``execution_options=["validate_only"]`` checks the change without making it;
* changes need the ``ads_management`` permission (Meta App Review for accounts AdVegaX's
  customers do not own). A connection's "Allow changes" asks for it (Q-10A-2).

A daily budget is changed only on a campaign that holds its own budget (Advantage campaign
budget); when the ad sets hold it, the engine refuses the change. A timeout, a lost answer or
a server error means the outcome is unknown (``UnknownOutcomeError``): the engine reads the
campaign back instead of sending the change again.
"""

from __future__ import annotations

import json
from typing import Any

from app.providers.base.changes import CampaignChange, CampaignSnapshot, ChangeKind, ChangeReceipt
from app.providers.base.errors import (
    InvalidRequestError,
    RateLimitedError,
    ResourceNotFoundError,
    ResponseTooLargeError,
    RetryableError,
    UnknownOutcomeError,
)
from app.providers.meta_ads import mapping
from app.providers.meta_ads.client import MetaGraphClient

ADS_MANAGEMENT = "ads_management"
WRITE_SCOPES = frozenset({ADS_MANAGEMENT})
CAMPAIGN_FIELDS = "id,status,effective_status,daily_budget,lifetime_budget"
STATUS_VALUES = {ChangeKind.PAUSE: "PAUSED", ChangeKind.RESUME: "ACTIVE"}


def read_campaign(
    graph: MetaGraphClient, token: str, campaign_id: str, currency: str
) -> CampaignSnapshot:
    found = mapping.object_id(campaign_id)
    if found is None:
        raise InvalidRequestError()
    row = graph.get(token, f"/{found}", {"fields": CAMPAIGN_FIELDS})
    if mapping.object_id(row.get("id")) != found:
        raise ResourceNotFoundError()
    budget = mapping.budget(row, "campaign", currency)
    return CampaignSnapshot(
        external_id=found,
        status=mapping.configured_status(row),
        # No budget of its own: the ad sets hold it (Meta has no shared budgets).
        budget_level="campaign" if budget else "ad_group",
        budget_period=budget.period if budget else None,
        daily_budget=budget.amount if budget and budget.period == "daily" else None,
        budget_external_id=budget.external_id if budget else None,
    )


def _fields(snapshot: CampaignSnapshot, change: CampaignChange, currency: str) -> dict[str, str]:
    if change.kind in STATUS_VALUES:
        return {"status": STATUS_VALUES[change.kind]}
    if change.kind is not ChangeKind.SET_DAILY_BUDGET or change.daily_budget is None:
        raise InvalidRequestError()
    if snapshot.budget_level != "campaign" or snapshot.budget_period != "daily":
        raise InvalidRequestError()
    units = change.daily_budget * mapping.offset(currency)
    if units != units.to_integral_value() or units <= 0:
        raise InvalidRequestError()
    return {"daily_budget": str(int(units))}


def change_campaign(
    graph: MetaGraphClient,
    token: str,
    snapshot: CampaignSnapshot,
    change: CampaignChange,
    currency: str,
    *,
    validate_only: bool,
) -> ChangeReceipt:
    node = mapping.object_id(snapshot.external_id)
    if node is None:
        raise InvalidRequestError()
    fields = _fields(snapshot, change, currency)
    form = dict(fields)
    if validate_only:
        form["execution_options"] = json.dumps(["validate_only"])
    sent: dict[str, Any] = {"method": "POST /<campaign>", **form}
    try:
        answer = graph.post_change(token, node, form)
    except RateLimitedError:
        raise  # refused before anything happened
    except (RetryableError, ResponseTooLargeError):
        raise UnknownOutcomeError() from None
    if not isinstance(answer, dict) or answer.get("success") is not True:
        raise UnknownOutcomeError()  # a 2xx without "success": look it up
    return ChangeReceipt(request=sent, answer={"success": True})
