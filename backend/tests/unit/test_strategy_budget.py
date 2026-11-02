"""Budget amounts (task 8-04, Q-8-5): AdVegaX computes them, they always add up exactly."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest
from app.domains.strategy.budget import (
    Budget,
    amounts,
    floor_reasons,
    minimum_reasons,
    out,
    share_reasons,
)

D = Decimal


@pytest.mark.parametrize(
    ("total", "currency", "shares", "expected"),
    [
        (
            "100.00",
            "AUD",
            {"google_ads": "60", "meta_ads": "40"},
            {"google_ads": "60.00", "meta_ads": "40.00"},
        ),
        # 3 x 33.33 % of 100.00: the cent left over goes to the first-listed largest remainder.
        (
            "100.00",
            "AUD",
            {"a": "33.33", "b": "33.33", "c": "33.34"},
            {"a": "33.33", "b": "33.33", "c": "33.34"},
        ),
        (
            "10.00",
            "AUD",
            {"a": "33.33", "b": "33.33", "c": "33.33"},
            {"a": "3.34", "b": "3.33", "c": "3.33"},
        ),
        (
            "1000",
            "JPY",
            {"google_ads": "33.33", "meta_ads": "66.67"},
            {"google_ads": "333", "meta_ads": "667"},
        ),
        (
            "50.005",
            "KWD",
            {"google_ads": "50", "meta_ads": "50"},
            {"google_ads": "25.003", "meta_ads": "25.002"},
        ),
    ],
)
def test_golden_amounts(total, currency, shares, expected):
    split = amounts(Budget(D(total), "daily", currency), {k: D(v) for k, v in shares.items()})
    assert {k: str(v) for k, v in split.items()} == expected
    assert sum(split.values()) == D(total)


def test_amounts_always_add_up_to_the_total():
    rng = random.Random(84)
    for _ in range(500):
        total = D(rng.randint(1, 10_000_000)) / 100
        first = D(rng.randint(1, 9998)) / 100
        shares = {"google_ads": first, "meta_ads": D(100) - first}
        split = amounts(Budget(total, "monthly", "AUD"), shares)
        assert sum(split.values()) == total
        assert all(v >= 0 for v in split.values())


@pytest.mark.parametrize(
    ("shares", "reasons"),
    [
        ({"a": "60", "b": "40"}, []),
        ({"a": "33.33", "b": "33.33", "c": "33.33"}, []),  # within the rounding tolerance
        ({"a": "60", "b": "30"}, ["shares_do_not_add_up"]),
        ({"a": "100", "b": "0"}, ["share_invalid:b"]),
        ({"a": "120", "b": "-20"}, ["share_invalid:a", "share_invalid:b"]),
    ],
)
def test_shares_must_be_positive_and_add_up(shares, reasons):
    assert share_reasons({k: D(v) for k, v in shares.items()}) == reasons


def test_platform_minimums_are_checked_on_the_daily_amount():
    monthly = Budget(D("300.00"), "monthly", "AUD")  # 9.87 a day
    split = amounts(monthly, {"google_ads": D(95), "meta_ads": D(5)})  # meta: 15.00 a month
    minimum = {"google_ads": D("1.50"), "meta_ads": D("1.50")}
    assert minimum_reasons(monthly, split, minimum) == ["below_platform_minimum:meta_ads"]
    assert minimum_reasons(monthly, split, {"google_ads": D(1), "meta_ads": None}) == [
        "budget_minimum_not_checkable:meta_ads"
    ]


def test_a_total_too_small_for_every_platform_is_refused_before_asking():
    platforms = ["google_ads", "meta_ads"]
    mins = {"google_ads": D("1.5"), "meta_ads": D("1.5")}
    assert floor_reasons(Budget(D("2.00"), "daily", "AUD"), platforms, mins) == ["budget_too_small"]
    assert floor_reasons(Budget(D("3.00"), "daily", "AUD"), platforms, mins) == []
    assert floor_reasons(Budget(D("3.00"), "daily", "AUD"), platforms, {"google_ads": None}) == [
        "budget_minimum_not_checkable"
    ]


def test_the_stored_form():
    budget = Budget(D("304.00"), "monthly", "AUD")
    split = amounts(budget, {"google_ads": D(75), "meta_ads": D(25)})
    assert out(budget, split) == {
        "google_ads": {"amount": "228.00", "daily": "7.50"},
        "meta_ads": {"amount": "76.00", "daily": "2.50"},
    }
