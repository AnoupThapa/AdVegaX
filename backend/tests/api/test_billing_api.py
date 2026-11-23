"""Billing against the Stripe simulator (Phase 13, tasks 13-02 … 13-06, PLAN §8 and §10).

The real ``StripeProvider`` talks to ``tests/stripe_sim.py`` through the safe HTTP client; the
simulator plays the customer (Checkout, the portal, failed and retried payments) and signs its
webhook events as Stripe does. Covers the trial, checkout and the portal (owners only), the
lifecycle (active, plan change, failed payment → grace → read-only → paid, cancel), webhooks
(signature, age, duplicates, any order, unknown events, Stripe unreachable), the nightly check,
reminders and notices, read-only mode, complimentary organizations, the limits and the setup
command. No call leaves the test process.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from app.domains.billing import entitlements, plans
from app.domains.billing import service as billing
from app.domains.billing import setup as billing_setup
from app.domains.notifications.email import memory

from tests.api.test_actions_api import rows
from tests.helpers import connected, last_email
from tests.stripe_sim import StripeSim

OWNER = "billing-owner@example.com"
HOOK = "/api/v1/billing/stripe/webhook"


@pytest.fixture
def sim(clock):
    s = StripeSim(clock=clock)
    s.seed_prices()
    return s


@pytest.fixture
def on(runtime, sim):
    runtime.settings = runtime.settings.model_copy(update={"BILLING_ENABLED": True})
    runtime.extras["billing_provider"] = sim.provider()
    return runtime


@pytest.fixture
def owner(on, make_client):
    c = make_client()
    c.signup(OWNER)
    c.org = c.create_org("Eve Zone")["id"]
    c.billing = f"/organizations/{c.org}/billing"
    return c


def view(c):
    response = c.get(c.billing)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def hook(c, event, *, signature=None):
    payload, signed = event
    return c.http.post(
        HOOK,
        content=payload,
        headers={"stripe-signature": signature or signed, "content-type": "application/json"},
    )


def subscribe(c, sim, plan="starter", interval="month"):
    response = c.post(f"{c.billing}/checkout", {"plan": plan, "interval": interval})
    assert response.status_code == 200, response.text
    session = response.json()["data"]["url"].rsplit("/", 1)[1]
    answer = hook(c, sim.pay(session))
    assert answer.status_code == 200, answer.text
    assert answer.json()["data"]["status"] == "applied"
    return sim.latest()["id"]


def later(c, clock, delta):
    """Move the clock on; sign in again (the session has timed out meanwhile)."""
    clock.advance(delta)
    assert c.login(OWNER).status_code == 200


def events(admin_engine):
    return rows(admin_engine, "SELECT * FROM billing_events ORDER BY received_at, stripe_event_id")


def code(response):
    return response.json()["error"]["code"]


# ------------------------------------------------------------------ off, trial, plans
def test_billing_off_changes_nothing(runtime, make_client):
    c = make_client()
    c.signup("off@example.com")
    org = c.create_org("Mediflex")["id"]
    data = c.get(f"/organizations/{org}/billing").json()["data"]
    assert data["enabled"] is False and data["status"] == "off" and data["plan"] is None
    assert data["read_only"] is False and data["checkout_available"] is False
    assert data["usage"] == {"stores": 0, "ad_accounts": 0, "members": 1, "ai_runs_today": 0}
    refused = c.post(
        f"/organizations/{org}/billing/checkout", {"plan": "growth", "interval": "month"}
    )
    assert refused.status_code == 503 and code(refused) == "BILLING_UNAVAILABLE"
    unsigned = c.http.post(HOOK, content=b"{}", headers={"content-type": "application/json"})
    assert unsigned.status_code == 503


def test_new_organization_starts_a_growth_trial(owner, clock):
    data = view(owner)
    assert data["enabled"] is True and data["status"] == "trialing"
    assert data["plan"]["code"] == "growth" and data["plan"]["limits"]["autopilot"] is True
    assert data["trial_ends_at"].startswith((clock.now() + timedelta(days=14)).date().isoformat())
    assert data["subscription_status"] == "none" and data["subscribed_plan"] is None
    assert data["can_manage"] is True and data["checkout_available"] is True
    assert data["portal_available"] is False
    listed = owner.get("/billing/plans").json()["data"]
    assert [(p["code"], p["monthly"], p["yearly"]) for p in listed] == [
        ("starter", 4900, 49000),
        ("growth", 14900, 149000),
        ("scale", 39900, 399000),
    ]
    assert listed[0]["currency"] == "aud"
    assert listed[0]["limits"] == {
        "stores": 1,
        "ad_accounts": 2,
        "members": 3,
        "ai_runs_per_day": 10,
        "autopilot": False,
    }


# ------------------------------------------------------------------ checkout and the portal
def test_checkout_subscribes_and_the_portal_opens(owner, sim, admin_engine):
    response = owner.post(f"{owner.billing}/checkout", {"plan": "starter", "interval": "year"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["url"].startswith("https://checkout.stripe.com/")
    (session,) = sim.sessions.values()
    assert session["line_items[0][price]"] == sim.price_of("advegax_starter_year")["id"]
    assert session["metadata[organization_id]"] == owner.org
    assert session["subscription_data[metadata][organization_id]"] == owner.org
    assert session["client_reference_id"] == owner.org
    assert session["automatic_tax[enabled]"] == "true"
    assert session["customer_email"] == OWNER and "customer" not in session
    assert session["success_url"].endswith(f"/orgs/{owner.org}/billing?checkout=done")
    (request,) = sim.calls("POST", "/v1/checkout/sessions")
    assert request.headers["stripe-version"] == "2026-09-30.basil"
    assert request.headers["idempotency-key"].startswith("checkout-")

    hook(owner, sim.pay(session["id"]))
    data = view(owner)
    assert data["status"] == "active" and data["plan"]["code"] == "starter"
    assert data["subscribed_plan"] == "starter" and data["interval"] == "year"
    assert data["subscription_status"] == "active" and data["trial_ends_at"] is None
    assert data["current_period_end"] and data["cancel_at_period_end"] is False
    assert data["checkout_available"] is False and data["portal_available"] is True
    again = owner.post(f"{owner.billing}/checkout", {"plan": "scale", "interval": "month"})
    assert again.status_code == 409 and code(again) == "CONFLICT"

    portal = owner.post(f"{owner.billing}/portal")
    assert portal.status_code == 200, portal.text
    assert portal.json()["data"]["url"].startswith("https://billing.stripe.com/")
    assert sim.portals[0]["return_url"].endswith(f"/orgs/{owner.org}/billing")
    assert "Starter plan, active" in last_email(OWNER, "billing changed").text
    audit = rows(
        admin_engine,
        "SELECT action, actor_type FROM audit_logs WHERE organization_id = :o "
        "AND action LIKE 'billing.%' ORDER BY created_at",
        o=uuid.UUID(owner.org),
    )
    assert {(a["action"], a["actor_type"]) for a in audit} == {
        ("billing.checkout_started", "user"),
        ("billing.subscription_changed", "system"),
        ("billing.portal_opened", "user"),
    }


def test_only_owners_manage_billing_but_everyone_sees_it(owner, make_client):
    admin = make_client()
    admin.signup("billing-admin@example.com")
    owner.invite_and_join(owner.org, admin, "billing-admin@example.com", "admin")
    data = admin.get(owner.billing).json()["data"]
    assert data["status"] == "trialing" and data["can_manage"] is False
    assert data["checkout_available"] is False
    for path, body in (("/checkout", {"plan": "starter", "interval": "month"}), ("/portal", None)):
        refused = admin.post(f"{owner.billing}{path}", body)
        assert refused.status_code == 403, path
    no_customer = owner.post(f"{owner.billing}/portal")
    assert no_customer.status_code == 409 and code(no_customer) == "CONFLICT"


def test_checkout_needs_the_price_and_stripe(owner, sim):
    sim.prices.clear()
    missing = owner.post(f"{owner.billing}/checkout", {"plan": "growth", "interval": "month"})
    assert missing.status_code == 503 and code(missing) == "BILLING_UNAVAILABLE"
    assert missing.json()["error"]["details"] == [{"reason": "price_missing"}]
    sim.seed_prices()
    sim.fail = 500
    down = owner.post(f"{owner.billing}/checkout", {"plan": "growth", "interval": "month"})
    assert down.status_code == 503 and code(down) == "BILLING_UNAVAILABLE"
    bad = owner.post(f"{owner.billing}/checkout", {"plan": "gold", "interval": "month"})
    assert bad.status_code == 422


# ------------------------------------------------------------------ webhooks
def test_forged_old_and_unsigned_events_are_refused_and_not_stored(owner, sim, admin_engine):
    event = sim.event("customer.subscription.updated", {"id": "sub_x", "object": "subscription"})
    payload, _ = event
    wrong = sim.sign(payload, secret="whsec_someone_else")
    old = sim.sign(payload, at=sim.stamp() - 600)
    for signature in (wrong, old, "t=abc,v1=00", "nonsense"):
        refused = hook(owner, event, signature=signature)
        assert refused.status_code == 401 and code(refused) == "INVALID_SIGNATURE", signature
    no_header = owner.http.post(HOOK, content=payload, headers={"content-type": "application/json"})
    assert no_header.status_code == 401
    assert events(admin_engine) == []


def test_a_repeated_event_is_applied_once(owner, sim, admin_engine):
    sub = subscribe(owner, sim)
    event = sim.change(sub, "advegax_growth_month")
    first, second = hook(owner, event), hook(owner, event)
    assert first.json()["data"]["status"] == "applied"
    assert second.json()["data"]["status"] == "duplicate"
    assert [e["result"] for e in events(admin_engine)] == ["applied", "applied"]
    assert view(owner)["subscribed_plan"] == "growth"
    changes = rows(
        admin_engine,
        "SELECT count(*) AS n FROM audit_logs WHERE action = 'billing.subscription_changed'",
    )
    assert changes[0]["n"] == 2  # subscribed, then changed — not three


def test_events_in_any_order_end_in_stripes_current_state(owner, sim):
    sub = subscribe(owner, sim)
    to_scale = sim.change(sub, "advegax_scale_month")
    back_to_growth = sim.change(sub, "advegax_growth_month")
    assert hook(owner, back_to_growth).status_code == 200
    assert hook(owner, to_scale).status_code == 200  # older, arriving late
    data = view(owner)
    assert data["subscribed_plan"] == "growth" and data["plan"]["code"] == "growth"


def test_unknown_events_and_strangers_are_ignored(owner, sim, admin_engine):
    unrelated = sim.event("customer.created", {"id": "cus_new", "object": "customer"})
    assert hook(owner, unrelated).json()["data"]["status"] == "ignored"
    stranger = sim.event(
        "customer.subscription.updated",
        {"id": "sub_stranger", "object": "subscription", "customer": "cus_stranger"},
    )
    assert hook(owner, stranger).json()["data"]["status"] == "ignored"
    nobody = sim.event(
        "invoice.paid",
        {"id": "in_1", "customer": "cus_x", "metadata": {"organization_id": str(uuid.uuid4())}},
    )
    assert hook(owner, nobody).json()["data"]["status"] == "ignored"
    assert {e["result"] for e in events(admin_engine)} == {"ignored"}
    assert view(owner)["status"] == "trialing"


def test_stripe_unreachable_is_retried_by_stripe(owner, sim, admin_engine):
    sub = subscribe(owner, sim)
    event = sim.change(sub, "advegax_scale_month")
    sim.fail = 503
    down = hook(owner, event)
    assert down.status_code == 503 and code(down) == "BILLING_UNAVAILABLE"
    failed = events(admin_engine)[-1]
    assert failed["result"] == "failed" and failed["error_code"] == "billing_unavailable"
    sim.fail = None
    assert hook(owner, event).json()["data"]["status"] == "applied"  # Stripe's retry
    assert view(owner)["subscribed_plan"] == "scale"


# ------------------------------------------------------------------ the lifecycle
def test_failed_payment_grace_read_only_and_paid_again(owner, sim, clock, on, admin_engine):
    sub = subscribe(owner, sim, "growth")
    hook(owner, sim.fail_payment(sub))
    data = view(owner)
    assert data["status"] == "past_due" and data["read_only"] is False
    assert data["plan"]["code"] == "growth"
    assert data["grace_ends_at"].startswith((clock.now() + timedelta(days=7)).date().isoformat())
    assert "Everything keeps working until" in last_email(OWNER, "payment failed").text
    # Still fully usable during the grace period.
    assert owner.put(f"/organizations/{owner.org}/optimization-settings", {}).status_code != 403

    later(owner, clock, timedelta(days=7, minutes=1))
    data = view(owner)
    assert data["status"] == "read_only" and data["read_only"] is True and data["plan"] is None
    refused = owner.post(f"/organizations/{owner.org}/connections/fake/start")
    assert refused.status_code == 403 and code(refused) == "ORGANIZATION_READ_ONLY"
    invite = owner.post(
        f"/organizations/{owner.org}/invitations", {"email": "x@example.com", "role": "viewer"}
    )
    assert invite.status_code == 403 and code(invite) == "ORGANIZATION_READ_ONLY"
    # Reading, the billing page, the portal and the organization's own name still work.
    assert owner.get(f"/organizations/{owner.org}/connections").status_code == 200
    assert owner.post(f"{owner.billing}/portal").status_code == 200
    assert owner.patch(f"/organizations/{owner.org}", {"name": "Eve Zone Pty"}).status_code == 200
    billing.tick(on)
    assert "is now read-only" in last_email(OWNER, "read-only").subject
    sent = len(memory.SENT)
    billing.tick(on)
    assert len(memory.SENT) == sent  # the notice is sent once

    hook(owner, sim.pay_again(sub))
    data = view(owner)
    assert data["status"] == "active" and data["read_only"] is False
    assert data["grace_ends_at"] is None
    (account,) = rows(admin_engine, "SELECT * FROM billing_accounts")
    assert account["first_failed_at"] is None and account["read_only_notice_sent_at"] is None


def test_cancel_at_period_end_then_read_only_after_the_trial(owner, sim, clock):
    sub = subscribe(owner, sim, "scale")
    hook(owner, sim.set(sub, cancel_at_period_end=True))
    data = view(owner)
    assert data["status"] == "active" and data["cancel_at_period_end"] is True
    assert "it ends on" in last_email(OWNER, "billing changed").text
    later(owner, clock, timedelta(days=31))
    hook(owner, sim.end(sub))
    data = view(owner)
    assert data["status"] == "read_only" and data["subscription_status"] == "canceled"
    assert data["checkout_available"] is True  # choose a plan again


def test_downgrade_keeps_what_exists(owner, sim, monkeypatch):
    monkeypatch.setitem(
        plans.PLANS,
        "starter",
        plans.Plan("starter", "Starter", 4900, plans.Limits(1, 1, 3, 10, False)),
    )
    sub = subscribe(owner, sim, "growth")
    conn = connected(owner, owner.org)
    resources = owner.get(f"/organizations/{owner.org}/connections/{conn}/resources")
    ids = [r["id"] for r in resources.json()["data"] if r["kind"] == "ad_account"]
    for rid in ids:
        assert owner.post(f"/organizations/{owner.org}/resources/{rid}/link").status_code == 201
    hook(owner, sim.change(sub, "advegax_starter_month"))
    data = view(owner)
    assert data["plan"]["code"] == "starter" and data["usage"]["ad_accounts"] == 2  # both kept
    unlinked = owner.post(f"/organizations/{owner.org}/resources/{ids[0]}/unlink")
    assert unlinked.status_code == 200
    again = owner.post(f"/organizations/{owner.org}/resources/{ids[0]}/link")
    assert again.status_code == 403 and code(again) == "PLAN_LIMIT_REACHED"


# ------------------------------------------------------------------ the trial ends
def test_trial_reminder_then_read_only(owner, clock, on):
    clock.advance(timedelta(days=10))
    assert billing.tick(on) == 0  # more than 3 days left
    clock.advance(timedelta(days=1, minutes=1))
    assert billing.tick(on) == 1
    assert "ends on" in last_email(OWNER, "trial").subject
    assert billing.tick(on) == 0  # once
    later(owner, clock, timedelta(days=3))
    assert view(owner)["status"] == "read_only"
    assert billing.tick(on) == 1
    assert "Nothing has been deleted" in last_email(OWNER, "read-only").text


def test_read_only_is_known_to_the_schedulers(owner, clock, on):
    org = uuid.UUID(owner.org)
    with on.db.transaction(org_id=org) as session:
        assert entitlements.is_read_only(on, session, org) is False
    clock.advance(timedelta(days=15))
    with on.db.transaction(org_id=org) as session:
        assert entitlements.is_read_only(on, session, org) is True
    on.settings = on.settings.model_copy(update={"BILLING_ENABLED": False})
    with on.db.transaction(org_id=org) as session:
        assert entitlements.is_read_only(on, session, org) is False  # rollback switch


def test_complimentary_organizations_are_never_charged(owner, on):
    on.settings = on.settings.model_copy(
        update={"BILLING_COMPLIMENTARY_ORGANIZATIONS": [uuid.UUID(owner.org)]}
    )
    data = view(owner)
    assert data["status"] == "complimentary" and data["plan"]["code"] == "scale"
    assert data["checkout_available"] is False and data["trial_ends_at"] is None
    refused = owner.post(f"{owner.billing}/checkout", {"plan": "starter", "interval": "month"})
    assert refused.status_code == 409


# ------------------------------------------------------------------ limits
def test_members_limit_counts_open_invitations(owner, sim):
    subscribe(owner, sim, "starter")  # 3 members
    for n in (1, 2):
        made = owner.post(
            f"/organizations/{owner.org}/invitations",
            {"email": f"m{n}@example.com", "role": "viewer"},
        )
        assert made.status_code == 201, made.text
    again = owner.post(
        f"/organizations/{owner.org}/invitations", {"email": "m1@example.com", "role": "viewer"}
    )
    assert again.status_code == 201  # the same person again replaces their invitation
    refused = owner.post(
        f"/organizations/{owner.org}/invitations", {"email": "m3@example.com", "role": "viewer"}
    )
    assert refused.status_code == 403 and code(refused) == "PLAN_LIMIT_REACHED"
    assert refused.json()["error"]["details"] == [
        {"limit": "members", "allowed": 3, "used": 3, "plan": "starter"}
    ]
    assert view(owner)["usage"]["members"] == 3


def test_ad_account_and_store_limits(owner, sim, monkeypatch):
    subscribe(owner, sim, "starter")
    monkeypatch.setitem(
        plans.PLANS,
        "starter",
        plans.Plan("starter", "Starter", 4900, plans.Limits(0, 1, 3, 10, False)),
    )
    conn = connected(owner, owner.org)
    found = owner.get(f"/organizations/{owner.org}/connections/{conn}/resources").json()["data"]
    accounts = [r["id"] for r in found if r["kind"] == "ad_account"]
    store = next(r["id"] for r in found if r["kind"] == "store")
    assert owner.post(f"/organizations/{owner.org}/resources/{accounts[0]}/link").status_code == 201
    second = owner.post(f"/organizations/{owner.org}/resources/{accounts[1]}/link")
    assert second.status_code == 403 and code(second) == "PLAN_LIMIT_REACHED"
    assert second.json()["error"]["details"][0]["limit"] == "ad_accounts"
    shop = owner.post(f"/organizations/{owner.org}/resources/{store}/link")
    assert shop.status_code == 403
    assert shop.json()["error"]["details"][0] == {
        "limit": "stores",
        "allowed": 0,
        "used": 0,
        "plan": "starter",
    }


def test_ai_runs_and_autopilot_follow_the_plan(owner, sim, on, clock):
    org = uuid.UUID(owner.org)
    with on.db.transaction(org_id=org) as session:
        assert entitlements.ai_runs_allowed(on, session, org) == min(on.settings.AI_DAILY_RUNS, 40)
        entitlements.require(on, session, org, "autopilot")  # Growth trial: allowed
    subscribe(owner, sim, "starter")
    with on.db.transaction(org_id=org) as session:
        assert entitlements.ai_runs_allowed(on, session, org) == min(on.settings.AI_DAILY_RUNS, 10)
        with pytest.raises(entitlements.PlanLimitReached) as caught:
            entitlements.require(on, session, org, "autopilot")
    assert caught.value.details == [{"limit": "autopilot", "plan": "starter"}]
    later(owner, clock, timedelta(days=60))
    hook(owner, sim.end(sim.latest()["id"]))
    with on.db.transaction(org_id=org) as session:
        assert entitlements.ai_runs_allowed(on, session, org) == 0
    enable = owner.post(f"/organizations/{owner.org}/autopilot/enable", {"confirm": "Eve Zone"})
    assert enable.status_code == 403 and code(enable) == "ORGANIZATION_READ_ONLY"


# ------------------------------------------------------------------ the nightly check
def test_the_nightly_check_corrects_a_missed_webhook(owner, sim, on, clock, admin_engine):
    sub = subscribe(owner, sim, "starter")
    sim.change(sub, "advegax_scale_year")  # the event never arrives
    assert billing.tick(on) >= 0
    data = view(owner)
    assert data["subscribed_plan"] == "scale" and data["interval"] == "year"
    (check,) = rows(admin_engine, "SELECT * FROM billing_reconciliations")
    assert check["checked"] == 1 and check["fixed"] == 1
    assert check["details"] == [{"organization_id": owner.org, "changed": ["plan", "interval"]}]
    billing.tick(on)
    assert len(rows(admin_engine, "SELECT id FROM billing_reconciliations")) == 1  # not yet due
    clock.advance(timedelta(days=1))
    sim.fail = 500
    billing.tick(on)
    latest = rows(
        admin_engine, "SELECT * FROM billing_reconciliations ORDER BY started_at DESC LIMIT 1"
    )[0]
    assert latest["fixed"] == 0
    assert latest["details"] == [{"organization_id": owner.org, "error": "billing_unavailable"}]


def test_a_subscription_gone_from_stripe_is_cancelled(owner, sim, on):
    sub = subscribe(owner, sim, "growth")
    del sim.subscriptions[sub]
    billing.reconcile(on)
    assert view(owner)["subscription_status"] == "canceled"


# ------------------------------------------------------------------ setup
def test_setup_creates_only_the_missing_prices(on, sim):
    sim.prices.clear()
    created = billing_setup.run(on)
    assert created == [
        "advegax_starter_month",
        "advegax_starter_year",
        "advegax_growth_month",
        "advegax_growth_year",
        "advegax_scale_month",
        "advegax_scale_year",
    ]
    yearly = sim.price_of("advegax_growth_year")
    assert yearly["unit_amount"] == 149000 and yearly["currency"] == "aud"
    assert yearly["tax_behavior"] == "inclusive" and yearly["recurring"]["interval"] == "year"
    assert len(sim.products) == 6
    assert billing_setup.run(on) == []
