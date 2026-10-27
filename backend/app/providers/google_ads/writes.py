"""Google Ads campaign changes — the only Google Ads write calls (Phase 10A, task 10A-03).

PHASE_10A_PLAN §4.1 (Google Ads API "Mutating resources", checked 2026-10-26; to confirm on the
test manager account in Step 0):

* a change is ``POST /vNN/customers/{customer_id}/{resources}:mutate`` with one ``update``
  operation and an ``updateMask`` naming the fields changed; ``validateOnly`` checks it
  without changing anything;
* pausing / resuming sets ``campaign.status`` to ``PAUSED`` / ``ENABLED``;
* a daily budget is the campaign's **campaign budget** (``amountMicros``), changed through
  ``campaignBudgets:mutate``. A budget shared by several campaigns is never changed here (the
  engine refuses it: it would change the other campaigns too).

Only the Action Engine reaches these functions, through the provider (static rule). One
operation per request, so a change is never half done. A timeout, a lost or unreadable answer
or a server error means the outcome is unknown (``UnknownOutcomeError``): the engine reads the
campaign back instead of sending the change again.
"""

from __future__ import annotations

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
from app.providers.base.types import AdAccountRef
from app.providers.google_ads import mapping
from app.providers.google_ads.client import GoogleAdsClient, valid_customer_id

# Reading one campaign with its budget (one operation). ``campaign_budget`` fields may be
# selected FROM campaign (an attributed resource).
CAMPAIGN = """
SELECT
  campaign.id,
  campaign.status,
  campaign.campaign_budget,
  campaign_budget.id,
  campaign_budget.amount_micros,
  campaign_budget.total_amount_micros,
  campaign_budget.period,
  campaign_budget.explicitly_shared
FROM campaign
WHERE campaign.id = {campaign_id}
""".strip()

STATUS_VALUES = {ChangeKind.PAUSE: "PAUSED", ChangeKind.RESUME: "ENABLED"}


def read_campaign(
    client: GoogleAdsClient, token: str, account: AdAccountRef, campaign_id: str
) -> CampaignSnapshot:
    cid = mapping.ident(campaign_id)
    if cid is None:
        raise InvalidRequestError()
    rows = client.search_stream(
        token,
        account.external_id,
        CAMPAIGN.format(campaign_id=cid),
        login_customer_id=account.access_hint,
    )
    for row in rows:
        data = row.get("campaign")
        if not isinstance(data, dict) or mapping.ident(data.get("id")) != cid:
            continue
        budget = mapping.budget(row) if isinstance(row.get("campaignBudget"), dict) else None
        return CampaignSnapshot(
            external_id=cid,
            status=mapping.status(data.get("status")),
            budget_level=budget.level if budget else None,
            budget_period=budget.period if budget else None,
            daily_budget=budget.amount if budget and budget.period == "daily" else None,
            budget_shared=bool(budget and budget.shared),
            budget_external_id=budget.external_id if budget else None,
        )
    raise ResourceNotFoundError()


def _operation(
    customer: str, snapshot: CampaignSnapshot, change: CampaignChange
) -> tuple[str, dict[str, Any]]:
    base = f"customers/{customer}"
    if change.kind in STATUS_VALUES:
        update = {
            "resourceName": f"{base}/campaigns/{snapshot.external_id}",
            "status": STATUS_VALUES[change.kind],
        }
        return "campaigns", {"update": update, "updateMask": "status"}
    budget_id = mapping.ident(snapshot.budget_external_id)
    if change.kind is not ChangeKind.SET_DAILY_BUDGET or change.daily_budget is None:
        raise InvalidRequestError()
    if budget_id is None or snapshot.budget_shared:
        raise InvalidRequestError()
    micros = change.daily_budget * mapping.MICROS
    if micros != micros.to_integral_value() or micros <= 0:
        raise InvalidRequestError()
    update = {
        "resourceName": f"{base}/campaignBudgets/{budget_id}",
        "amountMicros": str(int(micros)),
    }
    return "campaignBudgets", {"update": update, "updateMask": "amountMicros"}


def change_campaign(
    client: GoogleAdsClient,
    token: str,
    account: AdAccountRef,
    snapshot: CampaignSnapshot,
    change: CampaignChange,
    *,
    validate_only: bool,
) -> ChangeReceipt:
    customer = valid_customer_id(account.external_id)
    resources, operation = _operation(customer, snapshot, change)
    body = {"operations": [operation], "validateOnly": validate_only}
    path = f"/customers/{customer}/{resources}:mutate"
    sent = {"method": f"{resources}:mutate", **body}
    try:
        answer = client.post_change(token, path, body, login_customer_id=account.access_hint)
    except RateLimitedError:
        raise  # refused before anything happened
    except (RetryableError, ResponseTooLargeError):
        raise UnknownOutcomeError() from None
    results = answer.get("results") if isinstance(answer, dict) else None
    if not validate_only and (not isinstance(results, list) or len(results) != 1):
        raise UnknownOutcomeError()  # a 2xx without the one result: look it up
    return ChangeReceipt(request=sent, answer={"results": len(results or [])})
