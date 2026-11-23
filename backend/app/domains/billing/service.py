"""Billing: plans, checkout, the portal, webhooks, the nightly check and reminders (Phase 13,
tasks 13-03, 13-04 and 13-06, PHASE_13_PLAN Q-13-2 … Q-13-10; A32).

**Keeping in step with Stripe (Q-13-9).** A webhook is only a hint: its signature and age are
checked, it is recorded once by its event id (a repeat is answered and ignored), and AdVegaX
then **reads the subscription's current state from Stripe** and applies that. So events that
arrive twice or out of order always end in Stripe's current state, and a forged event — one
that somehow passed the signature check — could change nothing Stripe does not already say.
The nightly check reads every subscription again and fixes any difference (a missed webhook).

Calls to Stripe run **outside** database transactions; card details never reach AdVegaX
(Checkout and the portal are Stripe's own pages), and the keys are never logged or returned.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import BillingUnavailable, Conflict, InvalidWebhookSignature
from app.domains.ai.runs import runs_today
from app.domains.audit.service import Actor, record_audit
from app.domains.billing import entitlements
from app.domains.billing.models import (
    SUBSCRIPTION_STATUSES,
    BillingAccount,
    BillingEvent,
    BillingReconciliation,
)
from app.domains.billing.plans import PLANS, Plan, plan_of_lookup_key
from app.domains.billing.provider import (
    BillingError,
    BillingProvider,
    InvalidSignature,
    NewPrice,
    Subscription,
)
from app.domains.billing.schemas import (
    BillingOut,
    BillingUsageOut,
    CheckoutIn,
    PlanLimitsOut,
    PlanOut,
    RedirectOut,
)
from app.domains.billing.stripe import StripeProvider
from app.domains.identity.models import User
from app.domains.organizations.models import Membership, Organization
from app.domains.organizations.permissions import Permission, authorize, has_permission
from app.domains.organizations.tenancy import TenantContext
from app.providers.http.client import SafeHttpClient
from app.runtime import Runtime, outbound_policy

logger = logging.getLogger("advegax.billing")

SYSTEM = Actor("system", None)
LIVE = ("active", "trialing", "past_due", "unpaid", "incomplete", "paused")
ENDED = ("canceled", "incomplete_expired")
FAILING = ("past_due", "unpaid")
TRACKED = (
    "plan",
    "interval",
    "subscription_status",
    "current_period_end",
    "cancel_at_period_end",
)
STATUS_TEXT = {
    "active": "active",
    "trialing": "active",
    "past_due": "waiting for payment",
    "unpaid": "unpaid",
    "canceled": "cancelled",
    "incomplete": "waiting for the first payment",
    "incomplete_expired": "not started (the first payment did not go through)",
    "paused": "paused",
}


# ------------------------------------------------------------------ the provider
def provider_for(rt: Runtime) -> BillingProvider:
    """The configured provider (tests put the simulator in ``rt.extras["billing_provider"]``).
    Raises ``BillingUnavailable`` while billing is off or Stripe's key is not set."""
    injected = rt.extras.get("billing_provider")
    if injected is not None:
        return injected  # type: ignore[return-value]
    settings = rt.settings
    if not settings.BILLING_ENABLED or settings.STRIPE_SECRET_KEY is None:
        raise BillingUnavailable()
    policy = outbound_policy(settings)
    return StripeProvider(
        settings.STRIPE_SECRET_KEY,
        settings.STRIPE_WEBHOOK_SECRET,
        settings.STRIPE_API_VERSION,
        settings.STRIPE_WEBHOOK_TOLERANCE,
        lambda: SafeHttpClient(policy),
    )


def plan_out(rt: Runtime, plan: Plan) -> PlanOut:
    limits = plan.limits
    return PlanOut(
        code=plan.code,
        name=plan.name,
        currency=rt.settings.BILLING_CURRENCY,
        monthly=plan.monthly,
        yearly=plan.yearly,
        limits=PlanLimitsOut(
            stores=limits.stores,
            ad_accounts=limits.ad_accounts,
            members=limits.members,
            ai_runs_per_day=limits.ai_runs_per_day,
            autopilot=limits.autopilot,
        ),
    )


def _link(rt: Runtime, org_id: uuid.UUID, path: str = "/billing") -> str:
    return f"{rt.settings.APP_BASE_URL.rstrip('/')}/orgs/{org_id}{path}"


def _owners(session: Session, org_id: uuid.UUID) -> list[str]:
    return list(
        session.execute(
            select(User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.organization_id == org_id,
                Membership.role == "owner",
                Membership.status == "active",
            )
            .order_by(User.email)
        ).scalars()
    )


def notify(rt: Runtime, session: Session, org_id: uuid.UUID, template: str, **values: Any) -> None:
    org = session.get(Organization, org_id)
    for email in _owners(session, org_id):
        rt.notifications.send_email(
            session,
            template=template,
            recipient=email,
            organization_id=org_id,
            variables={
                "organization_name": org.name if org else "",
                "link": _link(rt, org_id),
                **values,
            },
        )


def _day(value: datetime | None) -> str:
    # "%-d" (day without a leading zero) is not valid on Windows, so the day is formatted by hand.
    return f"{value.day} {value:%B %Y}" if value else ""


# ------------------------------------------------------------------ applying Stripe's state
def _snapshot(account: BillingAccount) -> dict[str, Any]:
    return {
        "plan": account.plan,
        "interval": account.interval,
        "subscription_status": account.subscription_status,
        "current_period_end": account.current_period_end.isoformat()
        if account.current_period_end
        else None,
        "cancel_at_period_end": account.cancel_at_period_end,
    }


def apply(
    rt: Runtime,
    session: Session,
    account: BillingAccount,
    sub: Subscription | None,
    *,
    gone: bool = False,
) -> list[str]:
    """Make ``account`` match Stripe's subscription (``gone``: Stripe no longer has the one
    AdVegaX knew). Returns the names of the fields that changed; audits and tells the owners
    when something did."""
    now = rt.clock.now()
    before = _snapshot(account)
    was_failing = account.subscription_status in FAILING
    if sub is None:
        if gone:
            account.subscription_status = "canceled"
            account.cancel_at_period_end = False
    else:
        current = account.stripe_subscription_id
        if (
            current is not None
            and sub.id != current
            and sub.status in ENDED
            and account.subscription_status in LIVE
        ):
            return []  # news about an older subscription; the live one stands
        found = plan_of_lookup_key(sub.lookup_key)
        if found is None:
            logger.warning(
                "billing_unknown_price", extra={"organization_id": str(account.organization_id)}
            )
        account.stripe_subscription_id = sub.id
        account.stripe_customer_id = sub.customer_id
        account.plan, account.interval = (found[0].code, found[1]) if found else (None, None)
        status = sub.status if sub.status in SUBSCRIPTION_STATUSES else "incomplete"
        account.subscription_status = status
        account.current_period_end = sub.current_period_end
        account.cancel_at_period_end = sub.cancel_at_period_end
    failing = account.subscription_status in FAILING
    if failing and account.first_failed_at is None:
        account.first_failed_at = now
    if not failing:
        account.first_failed_at = None
    account.synced_at = now
    after = _snapshot(account)
    changed = [k for k in TRACKED if before[k] != after[k]]
    if not changed:
        return []
    account.updated_at = now
    if account.subscription_status in ("active", "trialing"):
        account.read_only_notice_sent_at = None
    org_id = account.organization_id
    record_audit(
        session,
        organization_id=org_id,
        actor=SYSTEM,
        action="billing.subscription_changed",
        resource_type="billing_account",
        resource_id=org_id,
        before=before,
        after=after,
    )
    if failing and not was_failing:
        grace = (account.first_failed_at or now) + rt.settings.BILLING_PAYMENT_GRACE
        notify(rt, session, org_id, "billing_payment_failed", grace_ends=_day(grace))
    else:
        plan = PLANS.get(account.plan or "")
        status_text = STATUS_TEXT.get(account.subscription_status, account.subscription_status)
        summary = f"{plan.name if plan else 'Your'} plan, {status_text}"
        if account.cancel_at_period_end and account.current_period_end:
            summary += f"; it ends on {_day(account.current_period_end)}"
        elif account.current_period_end and account.subscription_status in ("active", "trialing"):
            summary += f"; it renews on {_day(account.current_period_end)}"
        notify(rt, session, org_id, "billing_changed", summary=summary)
    return changed


def sync(
    rt: Runtime,
    provider: BillingProvider,
    org_id: uuid.UUID,
    *,
    subscription_id: str | None = None,
    customer_id: str | None = None,
) -> list[str] | None:
    """Read the organization's subscription from Stripe and apply it. Returns the changed
    fields, or None when there is nothing to read (or the organization does not exist)."""
    with rt.db.transaction(org_id=org_id) as session:
        if session.get(Organization, org_id) is None:
            return None
        account = entitlements.account_for(rt, session, org_id)
        known_sub, known_customer = account.stripe_subscription_id, account.stripe_customer_id
    target = subscription_id or known_sub
    customer = customer_id or known_customer
    sub: Subscription | None = None
    gone = False
    if target is not None:
        sub = provider.subscription(target)  # outside any transaction
        gone = sub is None and target == known_sub
    elif customer is not None:
        found = provider.subscriptions_of(customer)
        live = [s for s in found if s.status in LIVE]
        sub = (live or found)[0] if found else None
    else:
        return None
    with rt.db.transaction(org_id=org_id) as session:
        locked = session.get(BillingAccount, org_id, with_for_update=True)
        assert locked is not None
        account = locked
        if sub is None and not gone:
            if customer and account.stripe_customer_id is None:
                account.stripe_customer_id = customer
            account.synced_at = rt.clock.now()
            return []
        return apply(rt, session, account, sub, gone=gone)


# ------------------------------------------------------------------ webhooks (13-04)
def _organization_of(
    session: Session, event_org: str | None, sub: str | None, cus: str | None
) -> uuid.UUID | None:
    if event_org:
        try:
            return uuid.UUID(event_org)
        except ValueError:
            return None
    ids = [c for c in (sub, cus) if c]
    if not ids:
        return None
    found = session.execute(
        select(BillingAccount.organization_id).where(
            or_(
                BillingAccount.stripe_subscription_id.in_(ids),
                BillingAccount.stripe_customer_id.in_(ids),
            )
        )
    ).first()
    return found[0] if found else None


def _finish(
    rt: Runtime, event_id: str, org_id: uuid.UUID | None, result: str, error: str | None
) -> None:
    with rt.db.transaction(system=True) as session:
        row = session.get(BillingEvent, event_id, with_for_update=True)
        if row is not None:
            row.organization_id = org_id
            row.processed_at = rt.clock.now()
            row.result, row.error_code = result, error


def receive_webhook(rt: Runtime, payload: bytes, signature: str | None) -> str:
    """Verify, record once and apply one Stripe event. Returns applied | ignored | duplicate.
    A refused signature raises ``InvalidWebhookSignature`` (nothing stored); Stripe being
    unreachable raises ``BillingUnavailable`` so that Stripe sends the event again."""
    if not rt.settings.BILLING_ENABLED:
        raise BillingUnavailable()
    provider = provider_for(rt)
    try:
        event = provider.verify(payload, signature or "", rt.clock.now())
    except InvalidSignature:
        logger.warning("billing_webhook_refused")  # never the contents
        raise InvalidWebhookSignature() from None
    with rt.db.transaction(system=True) as session:
        added = session.execute(
            insert(BillingEvent)
            .values(
                stripe_event_id=event.id[:255],
                event_type=event.type[:128],
                received_at=rt.clock.now(),
            )
            .on_conflict_do_nothing(index_elements=["stripe_event_id"])
            .returning(BillingEvent.stripe_event_id)
        ).first()
        if added is None:
            seen = session.get(BillingEvent, event.id[:255])
            if seen is not None and seen.result in ("applied", "ignored"):
                return "duplicate"
        org_id = _organization_of(
            session, event.organization_id, event.subscription_id, event.customer_id
        )
    if not event.handled or org_id is None:
        _finish(rt, event.id[:255], org_id, "ignored", None)
        return "ignored"
    try:
        changed = sync(
            rt,
            provider,
            org_id,
            subscription_id=event.subscription_id,
            customer_id=event.customer_id,
        )
    except BillingError as exc:
        _finish(rt, event.id[:255], org_id, "failed", exc.code)
        logger.warning("billing_webhook_failed", extra={"error": exc.code})
        raise BillingUnavailable() from None
    if changed is None:
        _finish(rt, event.id[:255], None, "ignored", None)
        return "ignored"
    _finish(rt, event.id[:255], org_id, "applied", None)
    return "applied"


# ------------------------------------------------------------------ the nightly check
def reconcile(rt: Runtime) -> int:
    """Read every known subscription from Stripe and fix any difference. Returns how many
    accounts were corrected; the check itself is recorded in ``billing_reconciliations``."""
    if not rt.settings.BILLING_ENABLED:
        return 0
    try:
        provider = provider_for(rt)
    except BillingUnavailable:
        logger.warning("billing_reconcile_skipped", extra={"reason": "not_configured"})
        return 0
    started = rt.clock.now()
    with rt.db.transaction(system=True) as session:
        orgs = list(
            session.execute(
                select(BillingAccount.organization_id)
                .where(
                    or_(
                        BillingAccount.stripe_subscription_id.is_not(None),
                        BillingAccount.stripe_customer_id.is_not(None),
                    )
                )
                .order_by(BillingAccount.organization_id)
            ).scalars()
        )
    fixed = 0
    details: list[dict[str, Any]] = []
    for org_id in orgs:
        try:
            changed = sync(rt, provider, org_id)
        except BillingError as exc:
            details.append({"organization_id": str(org_id), "error": exc.code})
            continue
        if changed:
            fixed += 1
            details.append({"organization_id": str(org_id), "changed": changed})
    with rt.db.transaction(system=True) as session:
        session.add(
            BillingReconciliation(
                started_at=started, checked=len(orgs), fixed=fixed, details=details
            )
        )
    logger.info("billing_reconciled", extra={"checked": len(orgs), "fixed": fixed})
    return fixed


def reconcile_due(rt: Runtime) -> bool:
    with rt.db.transaction(system=True) as session:
        last = session.execute(select(func.max(BillingReconciliation.started_at))).scalar_one()
    return last is None or last <= rt.clock.now() - rt.settings.BILLING_RECONCILE_INTERVAL


# ------------------------------------------------------------------ the hourly tick
def tick(rt: Runtime) -> int:
    """Trial-ending reminders and read-only notices to owners; the nightly check when due.
    Returns how many emails were queued."""
    settings = rt.settings
    if not settings.BILLING_ENABLED:
        return 0
    with rt.db.transaction(system=True) as session:
        orgs = list(
            session.execute(
                select(BillingAccount.organization_id).order_by(BillingAccount.organization_id)
            ).scalars()
        )
    sent = 0
    for org_id in orgs:
        if org_id in settings.BILLING_COMPLIMENTARY_ORGANIZATIONS:
            continue
        with rt.db.transaction(org_id=org_id) as session:
            account = session.get(BillingAccount, org_id, with_for_update=True)
            if account is None or session.get(Organization, org_id) is None:
                continue
            now = rt.clock.now()
            now_standing = entitlements.standing(settings, org_id, account, now)
            trial_only = account.subscription_status in ("none", "canceled", "incomplete_expired")
            if (
                trial_only
                and account.trial_reminder_sent_at is None
                and account.stripe_subscription_id is None
                and now < account.trial_ends_at <= now + settings.BILLING_TRIAL_REMINDER
            ):
                account.trial_reminder_sent_at = now
                notify(
                    rt, session, org_id, "billing_trial_ending", ends=_day(account.trial_ends_at)
                )
                sent += 1
            if now_standing.read_only and account.read_only_notice_sent_at is None:
                account.read_only_notice_sent_at = now
                record_audit(
                    session,
                    organization_id=org_id,
                    actor=SYSTEM,
                    action="billing.read_only",
                    resource_type="billing_account",
                    resource_id=org_id,
                    after={"subscription_status": account.subscription_status},
                )
                notify(rt, session, org_id, "billing_read_only")
                sent += 1
            elif not now_standing.read_only and account.read_only_notice_sent_at is not None:
                account.read_only_notice_sent_at = None
    if reconcile_due(rt):
        reconcile(rt)
    return sent


# ------------------------------------------------------------------ the API (13-06)
class BillingService:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def plans(self) -> list[PlanOut]:
        return [plan_out(self.rt, p) for p in PLANS.values()]

    def get(self, ctx: TenantContext) -> BillingOut:
        authorize(ctx, Permission.BILLING_VIEW)
        rt, org_id = self.rt, ctx.organization_id
        with rt.db.transaction(org_id=org_id, user_id=ctx.user_id) as session:
            now = rt.clock.now()
            account = (
                entitlements.account_for(rt, session, org_id)
                if rt.settings.BILLING_ENABLED
                else None
            )
            now_standing = entitlements.standing(rt.settings, org_id, account, now)
            used = entitlements.usage(session, org_id, now)
            ai_today = runs_today(session, org_id, now)
        live = account is not None and account.subscription_status in LIVE
        complimentary = now_standing.status == "complimentary"
        can_manage = has_permission(ctx.role, Permission.BILLING_MANAGE)
        enabled = rt.settings.BILLING_ENABLED
        return BillingOut(
            enabled=enabled,
            status=now_standing.status,
            read_only=now_standing.read_only,
            plan=plan_out(rt, now_standing.plan) if now_standing.plan else None,
            subscribed_plan=account.plan if account else None,
            interval=account.interval if account else None,
            subscription_status=account.subscription_status if account else "none",
            trial_ends_at=account.trial_ends_at
            if account and not live and not complimentary
            else None,
            current_period_end=account.current_period_end if account and live else None,
            cancel_at_period_end=bool(account and live and account.cancel_at_period_end),
            grace_ends_at=now_standing.grace_ends_at,
            usage=BillingUsageOut(ai_runs_today=ai_today, **used),
            can_manage=can_manage,
            checkout_available=enabled and can_manage and not live and not complimentary,
            portal_available=bool(
                enabled and can_manage and account and account.stripe_customer_id
            ),
        )

    def checkout(self, ctx: TenantContext, body: CheckoutIn) -> RedirectOut:
        """Owners only: Stripe Checkout for one plan; the subscription arrives by webhook."""
        authorize(ctx, Permission.BILLING_MANAGE)
        rt, org_id = self.rt, ctx.organization_id
        if not rt.settings.BILLING_ENABLED:
            raise BillingUnavailable()
        if org_id in rt.settings.BILLING_COMPLIMENTARY_ORGANIZATIONS:
            raise Conflict("This organization is complimentary: there is nothing to pay.")
        with rt.db.transaction(org_id=org_id, user_id=ctx.user_id) as session:
            account = entitlements.account_for(rt, session, org_id)
            if account.subscription_status in LIVE:
                raise Conflict("Change or cancel your plan in Stripe's customer portal.")
            customer = account.stripe_customer_id
            user = session.get(User, ctx.user_id)
            email = user.email if user else None
        provider = provider_for(rt)
        plan = PLANS[body.plan]
        key = plan.lookup_key(body.interval)
        try:
            price = provider.prices([key]).get(key)
            if price is None:
                logger.warning("billing_price_missing", extra={"lookup_key": key})
                raise BillingUnavailable(details=[{"reason": "price_missing"}])
            url = provider.checkout(
                price_id=price,
                customer_id=customer,
                email=None if customer else email,
                organization_id=str(org_id),
                success_url=_link(rt, org_id, "/billing?checkout=done"),
                cancel_url=_link(rt, org_id, "/billing"),
                idempotency_key=f"checkout-{uuid.uuid4()}",
            )
        except BillingError as exc:
            logger.warning("billing_checkout_failed", extra={"error": exc.code})
            raise BillingUnavailable() from None
        with rt.db.transaction(org_id=org_id, user_id=ctx.user_id) as session:
            record_audit(
                session,
                organization_id=org_id,
                actor=Actor.user(ctx.user_id),
                action="billing.checkout_started",
                resource_type="billing_account",
                resource_id=org_id,
                after={"plan": plan.code, "interval": body.interval},
            )
        return RedirectOut(url=url)

    def portal(self, ctx: TenantContext) -> RedirectOut:
        """Owners only: Stripe's customer portal (card, invoices, change or cancel)."""
        authorize(ctx, Permission.BILLING_MANAGE)
        rt, org_id = self.rt, ctx.organization_id
        if not rt.settings.BILLING_ENABLED:
            raise BillingUnavailable()
        with rt.db.transaction(org_id=org_id, user_id=ctx.user_id) as session:
            customer = entitlements.account_for(rt, session, org_id).stripe_customer_id
        if customer is None:
            raise Conflict("Choose a plan first: there is nothing to manage in Stripe yet.")
        provider = provider_for(rt)
        try:
            url = provider.portal(customer_id=customer, return_url=_link(rt, org_id))
        except BillingError as exc:
            logger.warning("billing_portal_failed", extra={"error": exc.code})
            raise BillingUnavailable() from None
        with rt.db.transaction(org_id=org_id, user_id=ctx.user_id) as session:
            record_audit(
                session,
                organization_id=org_id,
                actor=Actor.user(ctx.user_id),
                action="billing.portal_opened",
                resource_type="billing_account",
                resource_id=org_id,
            )
        return RedirectOut(url=url)


# ------------------------------------------------------------------ setup (13-03)
def missing_prices(rt: Runtime, provider: BillingProvider) -> list[NewPrice]:
    wanted = {
        plan.lookup_key(interval): NewPrice(
            lookup_key=plan.lookup_key(interval),
            product_name=f"AdVegaX {plan.name} ({'monthly' if interval == 'month' else 'yearly'})",
            unit_amount=plan.price(interval),
            interval=interval,
            currency=rt.settings.BILLING_CURRENCY,
        )
        for plan in PLANS.values()
        for interval in ("month", "year")
    }
    found = provider.prices(list(wanted))
    return [p for key, p in wanted.items() if key not in found]
