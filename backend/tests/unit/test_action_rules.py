"""The Action Engine's catalogue and checks (Phase 10A, task 10A-02, Q-10A-1, Q-10A-4, Q-10A-5).

Pure functions: every check and bound, the order of the groups, undo and the comparisons the
worker relies on (read before write, verification, looking up an unknown outcome).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from app.domains.actions import catalogue, engine, validation
from app.domains.actions.catalogue import CATALOGUE, ParamsInvalid
from app.domains.actions.validation import Facts, Limits
from app.providers.base.changes import CampaignSnapshot
from app.providers.base.types import AdEntityStatus

PAUSE = CATALOGUE["campaign.pause"]
RESUME = CATALOGUE["campaign.resume"]
BUDGET = CATALOGUE["campaign.set_daily_budget"]


def snap(status=AdEntityStatus.ACTIVE, daily="50", level="campaign", period="daily", shared=False):
    return CampaignSnapshot(
        external_id="11",
        status=status,
        budget_level=level,
        budget_period=period,
        daily_budget=Decimal(daily) if daily is not None else None,
        budget_shared=shared,
        budget_external_id="501",
    )


def limits(**changes):
    values = {
        "increase_percent": 50,
        "decrease_percent": 90,
        "minimum": Decimal("1.60"),
        "maximum": Decimal("500"),
        "maximum_set": True,
        "budget_changed_recently": False,
        "volume_used": 0,
        "volume_limit": 50,
    }
    values.update(changes)
    return Limits(**values)


def checks(spec, params, snapshot=None, *, resource=None, params_reason=None, **limit_changes):
    return validation.run(
        Facts(
            spec=spec,
            params=params,
            params_reason=params_reason,
            resource_reason=resource,
            snapshot=snapshot if snapshot is not None else snap(),
            limits=limits(**limit_changes),
        )
    )


def failed(result):
    return [(c.check, c.reason) for c in result if c.result == "failed"]


# ------------------------------------------------------------------ the catalogue
def test_the_catalogue_is_closed():
    assert set(CATALOGUE) == {"campaign.pause", "campaign.resume", "campaign.set_daily_budget"}


@pytest.mark.parametrize(
    ("raw", "currency", "expected"),
    [
        ({"daily_budget": "60"}, "AUD", {"daily_budget": "60.00"}),
        ({"daily_budget": "60.5"}, "AUD", {"daily_budget": "60.50"}),
        ({"daily_budget": "6000"}, "JPY", {"daily_budget": "6000"}),
    ],
)
def test_budget_values(raw, currency, expected):
    assert catalogue.parse(BUDGET, raw, currency) == expected


@pytest.mark.parametrize(
    ("raw", "currency", "reason"),
    [
        ({}, "AUD", "daily_budget_required"),
        ({"daily_budget": "60", "x": "1"}, "AUD", "daily_budget_required"),
        ({"daily_budget": "0"}, "AUD", "daily_budget_invalid"),
        ({"daily_budget": "-1"}, "AUD", "daily_budget_invalid"),
        ({"daily_budget": "NaN"}, "AUD", "daily_budget_invalid"),
        ({"daily_budget": "Infinity"}, "AUD", "daily_budget_invalid"),
        ({"daily_budget": "1e13"}, "AUD", "daily_budget_invalid"),
        ({"daily_budget": "60.001"}, "AUD", "daily_budget_precision"),
        ({"daily_budget": "60.5"}, "JPY", "daily_budget_precision"),
        ({"daily_budget": True}, "AUD", "daily_budget_invalid"),
    ],
)
def test_refused_budget_values(raw, currency, reason):
    with pytest.raises(ParamsInvalid) as found:
        catalogue.parse(BUDGET, raw, currency)
    assert found.value.reason == reason


def test_pause_and_resume_take_no_values():
    assert catalogue.parse(PAUSE, {}, "AUD") == {}
    with pytest.raises(ParamsInvalid):
        catalogue.parse(RESUME, {"daily_budget": "5"}, "AUD")


def test_the_key_identifies_the_change():
    one = uuid.uuid4()
    assert catalogue.key(one, PAUSE, {}) == catalogue.key(one, PAUSE, {})
    assert catalogue.key(one, PAUSE, {}) != catalogue.key(one, RESUME, {})
    assert catalogue.key(one, BUDGET, {"daily_budget": "1.00"}) != catalogue.key(
        one, BUDGET, {"daily_budget": "2.00"}
    )
    assert catalogue.key(one, PAUSE, {}) != catalogue.key(uuid.uuid4(), PAUSE, {})


def test_undo_is_the_opposite_change():
    assert catalogue.undo(PAUSE, {})[0] is RESUME
    assert catalogue.undo(RESUME, {})[0] is PAUSE
    assert catalogue.undo(BUDGET, {"daily_budget": "50.00"}) == (BUDGET, {"daily_budget": "50.00"})
    assert catalogue.undo(BUDGET, {"daily_budget": None}) is None


def test_reached_and_same_state():
    assert catalogue.reached(PAUSE, {}, snap(AdEntityStatus.PAUSED))
    assert not catalogue.reached(PAUSE, {}, snap())
    assert catalogue.reached(BUDGET, {"daily_budget": "60.00"}, snap(daily="60"))
    assert not catalogue.reached(BUDGET, {"daily_budget": "60.00"}, snap(daily="61"))
    before = snap().as_json()
    assert catalogue.same_state(before, snap(daily="50.000000"))  # the same amount
    assert not catalogue.same_state(before, snap(daily="49"))
    assert not catalogue.same_state(before, snap(AdEntityStatus.PAUSED))
    assert not catalogue.same_state(before, snap(shared=True))


def test_stored_snapshots_come_back_unchanged():
    one = snap(AdEntityStatus.PAUSED, daily="12.34")
    assert engine.snapshot_of(engine.stored(one), "11") == one


# ------------------------------------------------------------------ the checks
def test_a_valid_pause_passes_every_group():
    result = checks(PAUSE, {})
    assert [(c.check, c.result) for c in result] == [
        ("shape", "passed"),
        ("resource", "passed"),
        ("limits", "passed"),
        ("state", "passed"),
    ]
    assert validation.passed(result)


def test_later_groups_are_skipped_after_a_failure():
    result = checks(PAUSE, None, params_reason="unexpected_values")
    assert [(c.check, c.result) for c in result] == [
        ("shape", "failed"),
        ("resource", "skipped"),
        ("limits", "skipped"),
        ("state", "skipped"),
    ]
    result = checks(PAUSE, {}, resource="account_not_linked")
    assert failed(result) == [("resource", "account_not_linked")]


@pytest.mark.parametrize(
    ("spec", "status", "reason"),
    [
        (PAUSE, AdEntityStatus.PAUSED, "already_paused"),
        (RESUME, AdEntityStatus.ACTIVE, "already_active"),
        (PAUSE, AdEntityStatus.REMOVED, "campaign_not_changeable"),
        (BUDGET, AdEntityStatus.ARCHIVED, "campaign_not_changeable"),
        (PAUSE, None, "campaign_not_changeable"),
    ],
)
def test_state(spec, status, reason):
    params = {"daily_budget": "55.00"} if spec is BUDGET else {}
    assert failed(checks(spec, params, snap(status))) == [("state", reason)]


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        (snap(level="ad_group", daily=None, period=None), "budget_on_ad_sets"),
        (snap(period="lifetime", daily=None), "budget_not_daily"),
        (snap(shared=True), "budget_shared"),
        (snap(daily="55"), "no_change"),
    ],
)
def test_who_holds_the_budget(snapshot, reason):
    assert failed(checks(BUDGET, {"daily_budget": "55.00"}, snapshot)) == [("budget", reason)]


@pytest.mark.parametrize(
    ("amount", "changes", "reasons"),
    [
        ("75.00", {}, []),  # +50 % exactly
        ("75.01", {}, ["increase_too_large"]),
        ("5.00", {}, []),  # -90 % exactly
        ("4.99", {}, ["decrease_too_large"]),
        ("60.00", {"minimum": Decimal("61")}, ["below_platform_minimum"]),
        ("60.00", {"minimum": None}, ["minimum_not_checkable"]),
        ("60.00", {"maximum": Decimal("59.99")}, ["above_maximum"]),
        ("60.00", {"maximum": None}, ["maximum_not_checkable"]),
        ("60.00", {"maximum": None, "maximum_set": False}, ["maximum_not_set"]),
        ("60.00", {"budget_changed_recently": True}, ["budget_changed_recently"]),
        ("60.00", {"volume_used": 50}, ["daily_limit_reached"]),
        ("80.00", {"volume_used": 50}, ["increase_too_large", "daily_limit_reached"]),
    ],
)
def test_limits(amount, changes, reasons):
    result = checks(BUDGET, {"daily_budget": amount}, **changes)
    assert [r for _, r in failed(result)] == reasons


def test_an_undo_has_no_step_or_frequency_limit():
    result = checks(
        BUDGET,
        {"daily_budget": "500.00"},
        snap(daily="50"),
        budget_changed_recently=True,
        undo=True,
    )
    assert validation.passed(result)
    result = checks(BUDGET, {"daily_budget": "501.00"}, snap(daily="50"), undo=True)
    assert failed(result) == [("limits", "above_maximum")]  # every other check still applies


def test_the_volume_limit_applies_to_every_change():
    assert failed(checks(PAUSE, {}, volume_used=50)) == [("limits", "daily_limit_reached")]


def test_failures_are_listed_for_the_error():
    result = checks(BUDGET, {"daily_budget": "80.00"})
    assert validation.failures(result) == [{"check": "limits", "reason": "increase_too_large"}]
