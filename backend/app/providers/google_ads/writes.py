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

import re
from typing import Any

from app.providers.base.changes import (
    COUNTRIES,
    BuildResult,
    CampaignBuild,
    CampaignChange,
    CampaignSnapshot,
    ChangeKind,
    ChangeReceipt,
)
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


# ------------------------------------------------------------------ campaign builder (10B)
# A whole Search campaign in one all-or-nothing ``googleAds:mutate`` with temporary resource
# names (parents first): budget, campaign (paused), locations, ad group, keywords, ad. Google
# "Get started with Search campaigns" (checked 2026-10-27; to confirm in Step 0).
_REFERENCE = re.compile(r"^AVX-[0-9A-F]{6}$")
MATCH_TYPES = {"phrase": "PHRASE", "exact": "EXACT", "broad": "BROAD"}


def _text_assets(lines: tuple[str, ...]) -> list[dict[str, str]]:
    return [{"text": line} for line in lines]


def build_operations(customer: str, build: CampaignBuild) -> list[dict[str, Any]]:
    base = f"customers/{customer}"
    budget, campaign, group = (
        f"{base}/campaignBudgets/-1",
        f"{base}/campaigns/-2",
        f"{base}/adGroups/-3",
    )
    micros = build.daily_budget * mapping.MICROS
    if micros != micros.to_integral_value() or micros <= 0:
        raise InvalidRequestError()
    bidding: dict[str, Any] = (
        {"maximizeConversions": {}} if build.maximize_conversions else {"targetSpend": {}}
    )
    operations: list[dict[str, Any]] = [
        {
            "campaignBudgetOperation": {
                "create": {
                    "resourceName": budget,
                    "name": f"{build.name} budget",
                    "amountMicros": str(int(micros)),
                    "deliveryMethod": "STANDARD",
                    "explicitlyShared": False,
                }
            }
        },
        {
            "campaignOperation": {
                "create": {
                    "resourceName": campaign,
                    "name": build.name,
                    "status": "PAUSED",  # nothing runs until "Go live" is approved
                    "advertisingChannelType": "SEARCH",
                    "campaignBudget": budget,
                    **bidding,
                    "networkSettings": {
                        "targetGoogleSearch": True,
                        "targetSearchNetwork": True,
                        "targetContentNetwork": False,
                        "targetPartnerSearchNetwork": False,
                    },
                    "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
                }
            }
        },
    ]
    for code in build.locations:
        constant = COUNTRIES.get(code)
        if constant is None:
            raise InvalidRequestError()
        operations.append(
            {
                "campaignCriterionOperation": {
                    "create": {
                        "campaign": campaign,
                        "location": {"geoTargetConstant": f"geoTargetConstants/{constant}"},
                    }
                }
            }
        )
    operations.append(
        {
            "adGroupOperation": {
                "create": {
                    "resourceName": group,
                    "name": f"{build.name} ad group",
                    "campaign": campaign,
                    "status": "ENABLED",
                    "type": "SEARCH_STANDARD",
                }
            }
        }
    )
    for keyword in build.keywords:
        operations.append(
            {
                "adGroupCriterionOperation": {
                    "create": {
                        "adGroup": group,
                        "status": "ENABLED",
                        "keyword": {"text": keyword.text, "matchType": MATCH_TYPES[keyword.match]},
                    }
                }
            }
        )
    ad: dict[str, Any] = {
        "finalUrls": [build.landing_url],
        "responsiveSearchAd": {
            "headlines": _text_assets(build.headlines),
            "descriptions": _text_assets(build.descriptions),
            **({"path1": build.path1} if build.path1 else {}),
            **({"path2": build.path2} if build.path2 else {}),
        },
    }
    operations.append(
        {"adGroupAdOperation": {"create": {"adGroup": group, "status": "ENABLED", "ad": ad}}}
    )
    return operations


_RESULT_KEYS = {
    "campaignBudgetResult": "budget",
    "campaignResult": "campaign",
    "adGroupResult": "ad_group",
    "adGroupAdResult": "ad",
}


def create_campaign(
    client: GoogleAdsClient,
    token: str,
    account: AdAccountRef,
    build: CampaignBuild,
    *,
    validate_only: bool,
) -> BuildResult:
    if not _REFERENCE.fullmatch(build.reference) or build.reference not in build.name:
        raise InvalidRequestError()
    customer = valid_customer_id(account.external_id)
    operations = build_operations(customer, build)
    body = {"mutateOperations": operations, "validateOnly": validate_only}
    sent = {
        "method": "googleAds:mutate",
        "operations": len(operations),
        "validateOnly": validate_only,
    }
    try:
        answer = client.post_change(
            token,
            f"/customers/{customer}/googleAds:mutate",
            body,
            login_customer_id=account.access_hint,
        )
    except RateLimitedError:
        raise
    except (RetryableError, ResponseTooLargeError):
        raise UnknownOutcomeError() from None
    if validate_only:
        return BuildResult(request=sent)
    responses = answer.get("mutateOperationResponses") if isinstance(answer, dict) else None
    if not isinstance(responses, list) or len(responses) != len(operations):
        raise UnknownOutcomeError()
    ids: dict[str, str] = {}
    for response in responses:
        for key, name in _RESULT_KEYS.items():
            found = (
                (response.get(key) or {}).get("resourceName")
                if isinstance(response, dict)
                else None
            )
            if found and name not in ids and (ident := mapping.resource_id(found)):
                ids[name] = ident
    if "campaign" not in ids or "budget" not in ids:
        raise UnknownOutcomeError()
    return BuildResult(ids=ids, request=sent)


FIND = """
SELECT
  campaign.id,
  campaign.name,
  campaign.status,
  campaign.campaign_budget
FROM campaign
WHERE campaign.name LIKE '%{reference}%'
""".strip()


def find_campaign(
    client: GoogleAdsClient, token: str, account: AdAccountRef, reference: str
) -> dict[str, str]:
    if not _REFERENCE.fullmatch(reference):
        raise InvalidRequestError()
    rows = client.search_stream(
        token,
        account.external_id,
        FIND.format(reference=reference),
        login_customer_id=account.access_hint,
    )
    for row in rows:
        data = row.get("campaign")
        if not isinstance(data, dict) or reference not in str(data.get("name", "")):
            continue
        if data.get("status") == "REMOVED":
            continue
        found = {"campaign": mapping.ident(data.get("id")) or ""}
        budget = mapping.resource_id(data.get("campaignBudget"))
        if budget:
            found["budget"] = budget
        return {k: v for k, v in found.items() if v}
    return {}


def remove_objects(
    client: GoogleAdsClient, token: str, account: AdAccountRef, ids: dict[str, str]
) -> ChangeReceipt:
    customer = valid_customer_id(account.external_id)
    sent: list[str] = []
    for resources, key in (("campaigns", "campaign"), ("campaignBudgets", "budget")):
        ident = mapping.ident(ids.get(key))
        if ident is None:
            continue
        body = {"operations": [{"remove": f"customers/{customer}/{resources}/{ident}"}]}
        try:
            client.post_change(
                token,
                f"/customers/{customer}/{resources}:mutate",
                body,
                login_customer_id=account.access_hint,
            )
        except RateLimitedError:
            raise
        except (RetryableError, ResponseTooLargeError):
            raise UnknownOutcomeError() from None
        sent.append(f"{resources}:mutate remove")
    return ChangeReceipt(request={"method": sent}, answer={"removed": len(sent)})
