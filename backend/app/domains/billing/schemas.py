"""Billing API schemas (Phase 13, task 13-06; API_SPECIFICATION §19N)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

PlanCode = Literal["starter", "growth", "scale"]
Interval = Literal["month", "year"]


class PlanLimitsOut(BaseModel):
    stores: int
    ad_accounts: int
    members: int  # active members and open invitations together
    ai_runs_per_day: int
    autopilot: bool


class PlanOut(BaseModel):
    code: PlanCode
    name: str
    currency: str  # ISO 4217, lower case (Stripe's form)
    monthly: int  # minor units, GST included for Australian customers
    yearly: int
    limits: PlanLimitsOut


class BillingUsageOut(BaseModel):
    stores: int
    ad_accounts: int
    members: int
    ai_runs_today: int


class BillingOut(BaseModel):
    enabled: bool  # BILLING_ENABLED: off = no limits, nothing charged
    # off | complimentary | trialing | active | past_due | read_only
    status: str
    read_only: bool
    plan: PlanOut | None  # the plan whose limits are in force (None: off or read-only)
    subscribed_plan: PlanCode | None  # what the Stripe subscription is for
    interval: Interval | None
    subscription_status: str  # Stripe's own word ("none": no subscription)
    trial_ends_at: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    grace_ends_at: datetime | None  # a failed payment: full use until then
    usage: BillingUsageOut
    can_manage: bool  # owners only (Q-13-5)
    checkout_available: bool  # no live subscription yet: choose a plan
    portal_available: bool  # a Stripe customer exists: manage in Stripe


class CheckoutIn(BaseModel):
    plan: PlanCode
    interval: Interval


class RedirectOut(BaseModel):
    url: str  # Stripe's own page (https)
