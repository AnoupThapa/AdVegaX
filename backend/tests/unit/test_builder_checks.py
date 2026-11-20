"""The campaign builder's checks and the platforms' create requests (Phase 10B, 10B-02/03)."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest
from app.domains.builder.checks import DraftFacts, keyword_reasons, landing_reason, run
from app.providers.base.changes import CampaignBuild, Keyword
from app.providers.base.errors import InvalidRequestError
from app.providers.google_ads import writes as google
from app.providers.meta_ads import writes as meta

BASE = DraftFacts(
    platform="google_ads",
    name="Gloves - Search - AVX-ABC123",
    daily_budget=Decimal("20.00"),
    currency="AUD",
    locations=["AU"],
    age_min=18,
    age_max=65,
    keywords=[{"text": "nitrile gloves", "match": "phrase"}],
    landing_url="https://shop.example/products/gloves",
    meta_page_id=None,
    meta_pixel_id=None,
    declared=True,
    creative_status="approved",
    creative_platform="google_ads",
    creative_from_strategy=True,
    strategy_status="ready",
    strategy_platforms=["google_ads", "meta_ads"],
    meta_image=False,
    store_hosts=["shop.example"],
    prohibited=["cure"],
    minimum=Decimal("1.60"),
    maximum=Decimal("500"),
    maximum_set=True,
)


def failed(facts):
    return [(c.check, c.reason) for c in run(facts) if c.result == "failed"]


def test_a_complete_draft_passes():
    assert failed(BASE) == []
    assert [c.check for c in run(BASE)] == [
        "creative",
        "keywords",
        "targeting",
        "landing_page",
        "budget",
        "meta",
        "declaration",
        "limits",
    ]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"resource_reason": "account_not_linked"}, ("creative", "account_not_linked")),
        ({"strategy_status": "draft"}, ("creative", "strategy_not_ready")),
        ({"strategy_platforms": ["meta_ads"]}, ("creative", "platform_not_in_strategy")),
        ({"creative_from_strategy": False}, ("creative", "creative_not_for_this_campaign")),
        ({"creative_status": "draft"}, ("creative", "creative_not_approved")),
        ({"name": " "}, ("creative", "name_invalid")),
        ({"locations": []}, ("targeting", "locations_required")),
        ({"locations": ["AU", "AU"]}, ("targeting", "location_not_supported")),
        ({"daily_budget": Decimal("1.555")}, ("budget", "daily_budget_invalid")),
        ({"daily_budget": Decimal("1.00")}, ("budget", "below_platform_minimum")),
        ({"minimum": None}, ("budget", "minimum_not_checkable")),
        ({"maximum": None}, ("budget", "maximum_not_checkable")),
        ({"maximum_set": False, "maximum": None}, ("budget", "maximum_not_set")),
        ({"daily_budget": Decimal("501")}, ("budget", "above_maximum")),
        ({"declared": False}, ("declaration", "declaration_required")),
        ({"volume_used": 50}, ("limits", "daily_limit_reached")),
    ],
)
def test_each_check(changes, expected):
    assert failed(replace(BASE, **changes)) == [expected]


def test_meta_needs_an_image_a_page_and_valid_ages():
    meta_facts = replace(BASE, platform="meta_ads", creative_platform="meta_ads", keywords=[])
    assert failed(meta_facts) == [("creative", "image_required")]
    meta_facts = replace(meta_facts, meta_image=True)
    assert failed(meta_facts) == [("meta", "page_required")]
    good = replace(meta_facts, meta_page_id="1122334455")
    assert failed(good) == []
    assert failed(replace(good, meta_pixel_id="x")) == [("meta", "pixel_invalid")]
    assert failed(replace(good, age_min=40, age_max=30)) == [("targeting", "ages_invalid")]


@pytest.mark.parametrize(
    ("keywords", "expected"),
    [
        ([], ["keywords_required"]),
        ([{"text": "a", "match": "phrase"}] * 21, ["too_many_keywords"]),
        ([{"text": "a", "match": "loose"}], ["match_type_invalid:0"]),
        ([{"text": " ", "match": "phrase"}], ["keyword_empty:0"]),
        ([{"text": "x" * 81, "match": "phrase"}], ["keyword_too_long:0"]),
        (
            [{"text": "one two three four five six seven eight nine ten eleven", "match": "exact"}],
            ["keyword_too_long:0"],
        ),
        ([{"text": "gloves, cheap", "match": "phrase"}], ["keyword_characters:0"]),
        (
            [
                {"text": "Nitrile  Gloves", "match": "phrase"},
                {"text": "nitrile gloves", "match": "phrase"},
            ],
            ["keyword_duplicate:1"],
        ),
        ([{"text": "gloves that cure", "match": "broad"}], ["keyword_prohibited:0"]),
    ],
)
def test_keywords(keywords, expected):
    assert keyword_reasons(keywords, ["cure"]) == expected


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("https://shop.example/x", None),
        ("https://www.shop.example/x", None),
        ("", "landing_url_required"),
        ("http://shop.example/x", "landing_url_not_https"),
        ("https://user:pw@shop.example/", "landing_url_invalid"),
        ("https://shop.example:8443/", "landing_url_invalid"),
        ("https://shop.example:bad/", "landing_url_invalid"),
        ("https://evil-shop.example/", "landing_url_not_store"),
        ("https://example/", "landing_url_not_store"),
    ],
)
def test_landing_pages(url, reason):
    assert landing_reason(url, ["shop.example"]) == reason


# ------------------------------------------------------------------ the create requests
BUILD = CampaignBuild(
    reference="AVX-ABC123",
    name="Gloves - Search - AVX-ABC123",
    daily_budget=Decimal("20.00"),
    locations=("AU", "NZ"),
    landing_url="https://shop.example/p",
    keywords=(Keyword("nitrile gloves", "phrase"),),
    headlines=("One", "Two", "Three"),
    descriptions=("First line.", "Second line."),
    path1="gloves",
    primary_text="Reliable gloves.",
    headline="Gloves",
    call_to_action="SHOP_NOW",
    page_id="1122334455",
)


def test_google_builds_one_ordered_request_with_temporary_names():
    ops = google.build_operations("1000000001", BUILD)
    kinds = [next(iter(op)) for op in ops]
    assert kinds == [
        "campaignBudgetOperation",
        "campaignOperation",
        "campaignCriterionOperation",
        "campaignCriterionOperation",
        "adGroupOperation",
        "adGroupCriterionOperation",
        "adGroupAdOperation",
    ]
    campaign = ops[1]["campaignOperation"]["create"]
    assert campaign["status"] == "PAUSED" and campaign["campaignBudget"].endswith("/-1")
    assert ops[0]["campaignBudgetOperation"]["create"]["amountMicros"] == "20000000"
    assert ops[2]["campaignCriterionOperation"]["create"]["location"] == {
        "geoTargetConstant": "geoTargetConstants/2036"
    }
    ad = ops[-1]["adGroupAdOperation"]["create"]["ad"]
    assert ad["responsiveSearchAd"]["path1"] == "gloves" and "path2" not in ad["responsiveSearchAd"]
    with pytest.raises(InvalidRequestError):
        google.build_operations("1", replace(BUILD, locations=("ZZ",)))
    with pytest.raises(InvalidRequestError):
        google.build_operations("1", replace(BUILD, daily_budget=Decimal("0.0000001")))


def test_meta_forms():
    campaign = meta.campaign_form(BUILD, "AUD")
    assert (campaign["status"], campaign["daily_budget"], campaign["special_ad_categories"]) == (
        "PAUSED",
        "2000",
        "[]",
    )
    assert (
        meta.campaign_form(replace(BUILD, daily_budget=Decimal(2000)), "JPY")["daily_budget"]
        == "2000"
    )
    with pytest.raises(InvalidRequestError):
        meta.campaign_form(replace(BUILD, daily_budget=Decimal("1.005")), "AUD")
    plain = meta.ad_set_form(BUILD, "1")
    assert plain["optimization_goal"] == "LINK_CLICKS" and "promoted_object" not in plain
    tracked = meta.ad_set_form(replace(BUILD, pixel_id="5566778899"), "1")
    assert json.loads(tracked["promoted_object"]) == {
        "pixel_id": "5566778899",
        "custom_event_type": "PURCHASE",
    }
    creative = json.loads(
        meta.creative_form(replace(BUILD, description="Free delivery"), "abc")["object_story_spec"]
    )
    assert creative["link_data"]["description"] == "Free delivery"
    assert creative["link_data"]["call_to_action"]["type"] == "SHOP_NOW"


def test_references_are_checked_before_anything_is_sent():
    with pytest.raises(InvalidRequestError):
        google.create_campaign(
            None, "t", None, replace(BUILD, reference="AVX-zz"), validate_only=True
        )  # type: ignore[arg-type]
    with pytest.raises(InvalidRequestError):
        meta.create_campaign(
            None, "t", "act_1", replace(BUILD, page_id="x"), "AUD", validate_only=True
        )  # type: ignore[arg-type]
    with pytest.raises(InvalidRequestError):
        meta.find_campaign(None, "t", "act_1", "nope")  # type: ignore[arg-type]
