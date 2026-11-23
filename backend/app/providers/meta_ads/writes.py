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

import base64
import json
import re
from typing import Any

from app.providers.base.changes import (
    BuildIncomplete,
    BuildResult,
    CampaignBuild,
    CampaignChange,
    CampaignSnapshot,
    ChangeKind,
    ChangeReceipt,
    MetaAsset,
)
from app.providers.base.errors import (
    InvalidRequestError,
    ProviderError,
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
# Reading the Pages a person may advertise as (Phase 10B): asked for with "Allow changes".
PAGES_SCOPE = "pages_show_list"
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


# ------------------------------------------------------------------ campaign builder (10B)
# Step by step, every object **paused**: the image (``/adimages`` → hash), the campaign
# (``OUTCOME_SALES``, the daily budget on the campaign), the ad set (countries, ages,
# purchases with a pixel or link clicks), the creative (Page, image, texts, call to action)
# and the ad. Each ID is reported as soon as it exists (``progress``); a stop part-way raises
# ``BuildIncomplete`` with what exists. Facts checked 2026-10-27; to confirm in Step 0.
_REFERENCE = re.compile(r"^AVX-[0-9A-F]{6}$")
_ACCOUNT = re.compile(r"^act_[0-9]{1,25}$")
FIND_EDGES = (("campaign", "campaigns"), ("ad_set", "adsets"), ("ad", "ads"))
LIVE_STATUSES = ["ACTIVE", "PAUSED", "ARCHIVED", "IN_PROCESS", "WITH_ISSUES"]


def _created(answer: Any) -> str:
    found = answer.get("id") if isinstance(answer, dict) else None
    if isinstance(found, int) and not isinstance(found, bool):
        found = str(found)
    if not isinstance(found, str) or not found.isdigit() or len(found) > 25:
        raise UnknownOutcomeError()
    return found


def _image_hash(answer: Any) -> str:
    images = answer.get("images") if isinstance(answer, dict) else None
    for image in (images or {}).values() if isinstance(images, dict) else ():
        found = image.get("hash") if isinstance(image, dict) else None
        if isinstance(found, str) and re.fullmatch(r"[0-9a-f]{8,64}", found):
            return found
    raise UnknownOutcomeError()


def _send(graph: MetaGraphClient, token: str, account: str, edge: str, form: dict[str, str]) -> Any:
    try:
        return graph.post_create(token, account, edge, form)
    except RateLimitedError:
        raise
    except (RetryableError, ResponseTooLargeError):
        raise UnknownOutcomeError() from None


def campaign_form(build: CampaignBuild, currency: str) -> dict[str, str]:
    units = build.daily_budget * mapping.offset(currency)
    if units != units.to_integral_value() or units <= 0:
        raise InvalidRequestError()
    return {
        "name": build.name,
        "objective": "OUTCOME_SALES",
        "status": "PAUSED",
        "special_ad_categories": json.dumps([]),  # declared by the person (Q-10B-10)
        "daily_budget": str(int(units)),
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
    }


def ad_set_form(build: CampaignBuild, campaign: str) -> dict[str, str]:
    targeting = {
        "geo_locations": {"countries": list(build.locations)},
        "age_min": build.age_min,
        "age_max": build.age_max,
    }
    form = {
        "name": f"{build.name} ad set",
        "campaign_id": campaign,
        "status": "PAUSED",
        "billing_event": "IMPRESSIONS",
        "targeting": json.dumps(targeting),
    }
    if build.pixel_id:
        form["optimization_goal"] = "OFFSITE_CONVERSIONS"
        form["promoted_object"] = json.dumps(
            {"pixel_id": build.pixel_id, "custom_event_type": "PURCHASE"}
        )
    else:
        form["optimization_goal"] = "LINK_CLICKS"
    return form


def creative_form(build: CampaignBuild, image_hash: str) -> dict[str, str]:
    link: dict[str, Any] = {
        "image_hash": image_hash,
        "link": build.landing_url,
        "message": build.primary_text,
        "name": build.headline,
        "call_to_action": {"type": build.call_to_action, "value": {"link": build.landing_url}},
    }
    if build.description:
        link["description"] = build.description
    return {
        "name": f"{build.name} creative",
        "object_story_spec": json.dumps({"page_id": build.page_id, "link_data": link}),
    }


def create_campaign(
    graph: MetaGraphClient,
    token: str,
    account: str,
    build: CampaignBuild,
    currency: str,
    *,
    validate_only: bool,
) -> BuildResult:
    if not _REFERENCE.fullmatch(build.reference) or build.reference not in build.name:
        raise InvalidRequestError()
    if not _ACCOUNT.fullmatch(account) or not mapping.object_id(build.page_id):
        raise InvalidRequestError()
    if build.pixel_id is not None and not mapping.object_id(build.pixel_id):
        raise InvalidRequestError()
    campaign = campaign_form(build, currency)
    if validate_only:  # the later objects need the earlier ones' IDs: the campaign is tested
        campaign["execution_options"] = json.dumps(["validate_only"])
        answer = _send(graph, token, account, "campaigns", campaign)
        if not isinstance(answer, dict) or answer.get("success") is not True:
            raise UnknownOutcomeError()
        return BuildResult(request={"method": "POST /act/campaigns", "validate_only": True})
    ids: dict[str, str] = {}
    steps: list[str] = []
    try:
        image = {"bytes": base64.b64encode(build.image).decode(), "name": f"{build.reference}.jpg"}
        ids["image"] = _image_hash(_send(graph, token, account, "adimages", image))
        steps.append("adimages")
        ids["campaign"] = _created(_send(graph, token, account, "campaigns", campaign))
        steps.append("campaigns")
        ad_set = ad_set_form(build, ids["campaign"])
        ids["ad_set"] = _created(_send(graph, token, account, "adsets", ad_set))
        steps.append("adsets")
        creative = creative_form(build, ids["image"])
        ids["creative"] = _created(_send(graph, token, account, "adcreatives", creative))
        steps.append("adcreatives")
        ad = {
            "name": f"{build.name} ad",
            "adset_id": ids["ad_set"],
            "creative": json.dumps({"creative_id": ids["creative"]}),
            "status": "PAUSED",
        }
        ids["ad"] = _created(_send(graph, token, account, "ads", ad))
        steps.append("ads")
    except (UnknownOutcomeError, ProviderError) as exc:
        raise BuildIncomplete(ids, exc) from None
    return BuildResult(ids=ids, request={"method": [f"POST /act/{s}" for s in steps]})


def find_campaign(
    graph: MetaGraphClient, token: str, account: str, reference: str
) -> dict[str, str]:
    """The campaign, ad set and ad whose name carries ``reference`` (reads only)."""
    if not _REFERENCE.fullmatch(reference) or not _ACCOUNT.fullmatch(account):
        raise InvalidRequestError()
    found: dict[str, str] = {}
    for key, edge in FIND_EDGES:
        rows = graph.get_all(
            token,
            f"/{account}/{edge}",
            {
                "fields": "id,name,status",
                "filtering": json.dumps(
                    [
                        {"field": "name", "operator": "CONTAIN", "value": reference},
                        {
                            "field": "effective_status",
                            "operator": "IN",
                            "value": LIVE_STATUSES,
                        },
                    ]
                ),
                "limit": "25",
            },
        )
        for row in rows:
            if reference in str(row.get("name", "")) and mapping.object_id(row.get("id")):
                found[key] = str(row["id"])
                break
    return found


def _set_status(
    graph: MetaGraphClient, token: str, ids: dict[str, str], keys: tuple[str, ...], status: str
) -> list[str]:
    done = []
    for key in keys:
        node = mapping.object_id(ids.get(key))
        if node is None:
            continue
        try:
            answer = graph.post_change(token, node, {"status": status})
        except RateLimitedError:
            raise
        except (RetryableError, ResponseTooLargeError):
            raise UnknownOutcomeError() from None
        if not isinstance(answer, dict) or answer.get("success") is not True:
            raise UnknownOutcomeError()
        done.append(key)
    return done


def go_live(graph: MetaGraphClient, token: str, ids: dict[str, str]) -> ChangeReceipt:
    """The ad, then the ad set, then the campaign: the campaign switched on last."""
    done = _set_status(graph, token, ids, ("ad", "ad_set", "campaign"), "ACTIVE")
    return ChangeReceipt(request={"method": "POST /<object>", "status": "ACTIVE", "objects": done})


def remove_objects(graph: MetaGraphClient, token: str, ids: dict[str, str]) -> ChangeReceipt:
    """Delete what a launch created (it is paused): the ad, ad set, then campaign."""
    done = _set_status(graph, token, ids, ("ad", "ad_set", "campaign"), "DELETED")
    return ChangeReceipt(request={"method": "POST /<object>", "status": "DELETED", "objects": done})


def pages(graph: MetaGraphClient, token: str) -> list[MetaAsset]:
    """The Facebook Pages the person can advertise as (``pages_show_list``)."""
    found = []
    for row in graph.get_all(token, "/me/accounts", {"fields": "id,name", "limit": "100"}):
        if (page := mapping.object_id(row.get("id"))) is not None:
            name = row.get("name")
            found.append(MetaAsset(page, name[:255] if isinstance(name, str) else None))
    return found


def pixels(graph: MetaGraphClient, token: str, account: str) -> list[MetaAsset]:
    if not _ACCOUNT.fullmatch(account):
        raise InvalidRequestError()
    found = []
    for row in graph.get_all(token, f"/{account}/adspixels", {"fields": "id,name", "limit": "100"}):
        if (pixel := mapping.object_id(row.get("id"))) is not None:
            name = row.get("name")
            found.append(MetaAsset(pixel, name[:255] if isinstance(name, str) else None))
    return found
