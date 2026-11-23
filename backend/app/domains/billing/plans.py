"""AdVegaX's plans, prices and limits (Phase 13, task 13-02, PHASE_13_PLAN Q-13-1; A32).

The starting prices and limits you approved. They are configuration: changing a number here
changes what AdVegaX sells and enforces; the matching Stripe prices are created by the setup
command (``python -m app.domains.billing.setup``) and found by their **lookup key**
(``advegax_<plan>_<interval>``), so no Stripe id is written in the code.

Prices are in the smallest unit of ``BILLING_CURRENCY`` (AUD cents) and **include GST** for
Australian customers (Stripe Tax, ``tax_behavior=inclusive``, Q-13-3).
"""

from __future__ import annotations

from dataclasses import dataclass

INTERVALS = ("month", "year")


@dataclass(frozen=True)
class Limits:
    stores: int
    ad_accounts: int
    members: int  # active members and open invitations together
    ai_runs_per_day: int
    autopilot: bool


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    monthly: int  # minor units
    limits: Limits

    @property
    def yearly(self) -> int:
        return self.monthly * 10  # two months free

    def price(self, interval: str) -> int:
        return self.monthly if interval == "month" else self.yearly

    def lookup_key(self, interval: str) -> str:
        return f"advegax_{self.code}_{interval}"


PLANS: dict[str, Plan] = {
    "starter": Plan("starter", "Starter", 4900, Limits(1, 2, 3, 10, False)),
    "growth": Plan("growth", "Growth", 14900, Limits(3, 6, 10, 40, True)),
    "scale": Plan("scale", "Scale", 39900, Limits(10, 20, 30, 150, True)),
}
COMPLIMENTARY_PLAN = "scale"


def plan_of_lookup_key(key: str | None) -> tuple[Plan, str] | None:
    """The plan and interval of a Stripe price's lookup key (None: not one of AdVegaX's)."""
    if not key or not key.startswith("advegax_"):
        return None
    parts = key.split("_")
    if len(parts) != 3 or parts[1] not in PLANS or parts[2] not in INTERVALS:
        return None
    return PLANS[parts[1]], parts[2]
