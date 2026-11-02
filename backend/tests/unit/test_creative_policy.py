"""Platform limits and the fixed checks (task 9-03, PLAN Q-9-4, Q-9-5)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.domains.creative.policy import BASE_PROHIBITED, blocking, check, flags
from app.domains.creative.specs import length

PRICES = [Decimal("19.95"), Decimal("1200.00")]

GOOGLE = {
    "headlines": ["Nitrile Gloves in Bulk", "Box of 100 for $19.95", "Fast Australian Delivery"],
    "descriptions": [
        "Powder-free nitrile gloves for clinics, kitchens and cleaners.",
        "Order online today and get free delivery on orders over $1,200.00.",
    ],
    "path1": "gloves",
    "path2": "nitrile",
}
META = {
    "primary_texts": ["Reliable nitrile gloves for busy kitchens and clinics."],
    "headlines": ["Bulk nitrile gloves"],
    "descriptions": ["Free delivery"],
    "call_to_action": "SHOP_NOW",
}


def run(fmt, content, *, prohibited=(), caps=(), prices=PRICES):
    return check(fmt, content, prohibited=list(prohibited), allowed_caps=list(caps), prices=prices)


def codes(results):
    return [(r["code"], r["field"]) for r in results]


def with_(base, **changes):
    return {**base, **changes}


def test_good_creatives_pass():
    assert run("google_rsa", GOOGLE) == []
    assert run("meta_single", META) == []


def test_wide_characters_count_twice():
    assert length("手袋") == 4
    assert length("Gloves") == 6
    assert codes(
        run("google_rsa", with_(GOOGLE, headlines=[*GOOGLE["headlines"][:2], "手" * 16]))
    ) == [("too_long", "headlines[2]")]


@pytest.mark.parametrize(
    ("fmt", "changes", "expected"),
    [
        ("google_rsa", {"headlines": ["One", "Two"]}, [("too_few", "headlines")]),
        (
            "google_rsa",
            {"headlines": [f"Headline {i}" for i in range(16)]},
            [("too_many", "headlines")],
        ),
        ("google_rsa", {"headlines": ["x" * 31, "Two", "Three"]}, [("too_long", "headlines[0]")]),
        (
            "google_rsa",
            {"descriptions": ["Only one description here."]},
            [("too_few", "descriptions")],
        ),
        ("google_rsa", {"path1": "x" * 16}, [("too_long", "path1")]),
        ("google_rsa", {"path1": "two words"}, [("invalid_path", "path1")]),
        ("google_rsa", {"headlines": ["Same", "same ", "Other"]}, [("duplicate", "headlines[1]")]),
        (
            "meta_single",
            {"call_to_action": "BUY_EVERYTHING"},
            [("unknown_value", "call_to_action")],
        ),
        ("meta_single", {"primary_texts": ["x" * 126]}, [("too_long", "primary_texts[0]")]),
        ("meta_single", {"headlines": []}, [("too_few", "headlines")]),
        ("meta_single", {"headlines": ["   "]}, [("empty", "headlines[0]")]),
    ],
)
def test_limits(fmt, changes, expected):
    base = GOOGLE if fmt == "google_rsa" else META
    assert codes(run(fmt, with_(base, **changes))) == expected


def test_wrong_shape():
    assert codes(run("google_rsa", {"headlines": []})) == [("shape", "content")]
    assert codes(run("google_rsa", "not a dict")) == [("shape", "content")]
    assert codes(run("meta_single", with_(META, headlines="one"))) == [("shape", "headlines")]
    assert codes(run("google_rsa", with_(GOOGLE, path1=None))) == [("shape", "path1")]


@pytest.mark.parametrize(
    ("line", "code"),
    [
        ("Call 02 9876 5432 today", "phone_number"),
        ("Call +61 400 123 456", "phone_number"),
        ("Visit evezone.com.au now", "web_address"),
        ("See www.example.org", "web_address"),
        ("Email sales@evezone.com.au", "email_address"),
        ("Gloves for you \U0001f600", "emoji"),
        ("HUGE glove sale", "all_caps"),
        ("Order now!!", "repeated_punctuation"),
        ("Gloves that cure dermatitis", "prohibited_term"),
        ("100% Effective against germs", "prohibited_term"),
        ("TGA approved gloves", "prohibited_term"),
        ("Now only $14.95 a box", "price_not_in_catalogue"),
        ("Only AUD 9 a box", "price_not_in_catalogue"),
        ("bad\x07text", "invalid_text"),
    ],
)
def test_google_text_rules(line, code):
    content = with_(GOOGLE, headlines=[line[:30], *GOOGLE["headlines"][1:]])
    if len(line) > 30:
        content = with_(GOOGLE, descriptions=[line, GOOGLE["descriptions"][0]])
    assert code in [r["code"] for r in blocking(run("google_rsa", content))]


def test_meta_allows_addresses_but_not_claims():
    content = with_(META, primary_texts=["Visit evezone.com.au or call 02 9876 5432."])
    assert run("meta_single", content) == []
    claim = with_(META, primary_texts=["Kills viruses on contact."])
    assert codes(run("meta_single", claim)) == [("prohibited_term", "primary_texts[0]")]


def test_the_organizations_own_words():
    content = with_(
        GOOGLE, headlines=["EVE Zone Gloves", "Hospital grade quality", "Fast delivery"]
    )
    assert codes(run("google_rsa", content)) == [("all_caps", "headlines[0]")]
    assert run("google_rsa", content, caps=["eve"]) == []
    assert codes(run("google_rsa", content, prohibited=["hospital grade"])) == [
        ("all_caps", "headlines[0]"),
        ("prohibited_term", "headlines[1]"),
    ]


def test_terms_match_whole_words_only():
    content = with_(META, primary_texts=["Secure, curated range of gloves."])  # not "cure"
    assert run("meta_single", content) == []


def test_prices_must_match_the_catalogue():
    assert run("meta_single", with_(META, primary_texts=["Boxes from $19.95."])) == []
    wrong = run("meta_single", with_(META, primary_texts=["Boxes from $18.95."]))
    assert [(r["code"], r["detail"]) for r in wrong] == [("price_not_in_catalogue", "18.95")]
    unknown = run("meta_single", with_(META, primary_texts=["Boxes from $19.95."]), prices=[])
    assert [r["code"] for r in unknown] == ["price_not_in_catalogue"]


def test_superlatives_are_flagged_not_blocked():
    results = run("meta_single", with_(META, headlines=["The best gloves in town"]))
    assert blocking(results) == []
    assert [(r["code"], r["detail"]) for r in flags(results)] == [("superlative", "best")]


def test_the_base_list_is_lower_case_and_unique():
    assert len(set(BASE_PROHIBITED)) == len(BASE_PROHIBITED)
    assert all(t == t.lower().strip() for t in BASE_PROHIBITED)
