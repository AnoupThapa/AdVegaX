"""Billing rules without a database (Phase 13): plans and lookup keys, what is in force, Stripe's
answers in both shapes, signatures and the provider's error handling."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from app.core.settings import Settings
from app.domains.billing.entitlements import standing
from app.domains.billing.plans import PLANS, plan_of_lookup_key
from app.domains.billing.provider import BillingError, InvalidSignature
from app.domains.billing.stripe import check_signature, event_of, subscription_of

from tests.stripe_sim import WEBHOOK_SECRET, StripeSim

NOW = datetime(2026, 11, 1, tzinfo=UTC)
ORG = uuid.uuid4()


def settings(**changes):
    return Settings().model_copy(update={"BILLING_ENABLED": True, **changes})


def account(**values):
    base = {
        "plan": None,
        "subscription_status": "none",
        "trial_ends_at": NOW + timedelta(days=3),
        "first_failed_at": None,
    }
    return SimpleNamespace(**{**base, **values})


def test_plans_and_lookup_keys():
    assert PLANS["growth"].yearly == 149000 and PLANS["growth"].price("month") == 14900
    assert PLANS["scale"].lookup_key("year") == "advegax_scale_year"
    assert plan_of_lookup_key("advegax_starter_month") == (PLANS["starter"], "month")
    for bad in (None, "", "other_starter_month", "advegax_gold_month", "advegax_scale_week"):
        assert plan_of_lookup_key(bad) is None
    assert plan_of_lookup_key("advegax_scale_year_x") is None


def test_what_is_in_force():
    s = settings()
    assert standing(settings(BILLING_ENABLED=False), ORG, None, NOW).status == "off"
    free = standing(settings(BILLING_COMPLIMENTARY_ORGANIZATIONS=[ORG]), ORG, None, NOW)
    assert free.status == "complimentary" and free.plan == PLANS["scale"]
    assert standing(s, ORG, None, NOW).plan == PLANS["growth"]
    trial = standing(s, ORG, account(), NOW)
    assert trial.status == "trialing" and not trial.read_only
    over = standing(s, ORG, account(trial_ends_at=NOW), NOW)
    assert over.status == "read_only" and over.read_only and over.plan is None
    paid = standing(s, ORG, account(plan="starter", subscription_status="active"), NOW)
    assert paid.status == "active" and paid.plan == PLANS["starter"]
    failed = account(plan="growth", subscription_status="past_due", first_failed_at=NOW)
    grace = standing(s, ORG, failed, NOW + timedelta(days=6))
    assert grace.status == "past_due" and grace.grace_ends_at == NOW + timedelta(days=7)
    assert standing(s, ORG, failed, NOW + timedelta(days=7)).read_only
    unknown = account(plan=None, subscription_status="active", trial_ends_at=NOW)
    assert standing(s, ORG, unknown, NOW).read_only  # an unknown price never grants limits


def test_settings_reject_an_unknown_trial_plan():
    with pytest.raises(ValueError):
        Settings(BILLING_TRIAL_PLAN="gold")
    parsed = Settings(BILLING_COMPLIMENTARY_ORGANIZATIONS=f"{ORG}, {ORG}")
    assert parsed.BILLING_COMPLIMENTARY_ORGANIZATIONS == [ORG, ORG]


def test_subscriptions_in_both_shapes():
    old = subscription_of(
        {
            "id": "sub_1",
            "customer": {"id": "cus_1"},
            "status": "active",
            "current_period_end": 1_800_000_000,
            "items": {"data": [{"price": {"lookup_key": "advegax_growth_month"}}]},
            "metadata": {"organization_id": str(ORG)},
        }
    )
    assert old.customer_id == "cus_1" and old.lookup_key == "advegax_growth_month"
    assert old.current_period_end == datetime.fromtimestamp(1_800_000_000, UTC)
    assert old.organization_id == str(ORG)
    new = subscription_of(
        {
            "id": "sub_2",
            "customer": "cus_2",
            "items": {"data": [{"price": {}, "current_period_end": 1_800_000_001}]},
        }
    )
    assert new.status == "incomplete" and new.lookup_key is None
    assert new.current_period_end == datetime.fromtimestamp(1_800_000_001, UTC)
    assert subscription_of({"id": "sub_3", "customer": "c"}).current_period_end is None


def test_events_in_both_invoice_shapes():
    def event(kind, obj):
        return event_of({"id": "evt_1", "type": kind, "data": {"object": obj}})

    paid = event("invoice.paid", {"subscription": "sub_1", "customer": "cus_1"})
    assert paid.subscription_id == "sub_1" and paid.handled
    nested = event(
        "invoice.payment_failed",
        {"customer": "cus_1", "parent": {"subscription_details": {"subscription": "sub_2"}}},
    )
    assert nested.subscription_id == "sub_2" and nested.customer_id == "cus_1"
    done = event(
        "checkout.session.completed",
        {"subscription": "sub_3", "customer": "cus_3", "client_reference_id": str(ORG)},
    )
    assert done.organization_id == str(ORG) and done.subscription_id == "sub_3"
    updated = event("customer.subscription.updated", {"id": "sub_4", "metadata": {}})
    assert updated.subscription_id == "sub_4" and updated.organization_id is None
    other = event("customer.created", {"id": "cus_5", "customer": {"id": "x"}})
    assert not other.handled and other.customer_id is None and other.subscription_id is None


def test_signatures():
    payload = b'{"id": "evt_1"}'
    t = int(NOW.timestamp())
    sim = StripeSim()
    good = sim.sign(payload, at=t)
    tolerance = timedelta(minutes=5)
    check_signature(payload, good, WEBHOOK_SECRET, NOW, tolerance)
    rotated = f"t={t},v1={'0' * 64},{good.split(',')[1]}"  # several v1 during secret rotation
    check_signature(payload, rotated, WEBHOOK_SECRET, NOW, tolerance)
    for header in (
        good.replace("t=", "x="),
        f"t={t},t={t},{good.split(',')[1]}",
        f"t={t}",
        sim.sign(payload, at=t, secret="whsec_other"),
        sim.sign(payload, at=t + 301),
    ):
        with pytest.raises(InvalidSignature):
            check_signature(payload, header, WEBHOOK_SECRET, NOW, tolerance)
    with pytest.raises(InvalidSignature):
        check_signature(payload + b" ", good, WEBHOOK_SECRET, NOW, tolerance)


class Clock:
    def now(self):
        return NOW


def test_provider_verify_needs_a_secret_and_an_event():
    sim = StripeSim(clock=Clock())
    payload, header = sim.event("invoice.paid", {"subscription": "sub_1"})
    assert sim.provider().verify(payload, header, NOW).subscription_id == "sub_1"
    with pytest.raises(InvalidSignature):
        sim.provider(webhook_secret=None).verify(payload, header, NOW)
    for body in (b"not json", b"[]", json.dumps({"type": "x"}).encode()):
        with pytest.raises(InvalidSignature):
            sim.provider().verify(body, sim.sign(body), NOW)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, "billing_key_refused"),
        (403, "billing_key_refused"),
        (429, "billing_unavailable"),
        (500, "billing_unavailable"),
        (400, "billing_request_refused"),
    ],
)
def test_provider_errors(status, error):
    sim = StripeSim(clock=Clock())
    sim.fail = status
    with pytest.raises(BillingError) as caught:
        sim.provider().prices(["advegax_starter_month"])
    assert caught.value.code == error


def test_provider_answers():
    sim = StripeSim(clock=Clock())
    provider = sim.provider()
    assert provider.subscription("sub_missing") is None  # 404: gone
    with pytest.raises(BillingError) as caught:
        provider.subscription("../v1/customers")
    assert caught.value.code == "billing_request_refused"
    assert provider.subscriptions_of("cus_none") == []
    (request,) = sim.calls("GET", "/v1/subscriptions")
    assert request.url.params["status"] == "all"

    def odd(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>")

    sim.handler = odd  # type: ignore[method-assign]
    with pytest.raises(BillingError) as caught:
        provider.prices([])
    assert caught.value.code == "billing_unexpected_response"
    sim.handler = lambda request: httpx.Response(200, json=[1])  # type: ignore[method-assign]
    with pytest.raises(BillingError):
        provider.prices([])
    sim.handler = lambda request: httpx.Response(200, json={"url": "http://x"})  # type: ignore[method-assign]
    with pytest.raises(BillingError):
        provider.portal(customer_id="cus_1", return_url="https://app")
    with pytest.raises(BillingError):
        provider.checkout(
            price_id="price_1",
            customer_id="cus_1",
            email=None,
            organization_id=str(ORG),
            success_url="https://app/ok",
            cancel_url="https://app/no",
            idempotency_key="k",
        )
