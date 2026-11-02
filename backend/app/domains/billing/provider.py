"""The billing-provider interface (Phase 13, task 13-03, PHASE_13_PLAN §3; D19).

AdVegaX's billing logic speaks only to this interface; Stripe is its first implementation
(``billing/stripe.py``). Card details never pass through it: checkout and the customer portal
are the provider's own pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class BillingError(Exception):
    """The provider could not be reached or refused the request (``code`` says which)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class InvalidSignature(BillingError):
    def __init__(self) -> None:
        super().__init__("invalid_signature")


@dataclass(frozen=True)
class Subscription:
    id: str
    customer_id: str
    status: str
    lookup_key: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    organization_id: str | None  # from the metadata AdVegaX set at checkout


@dataclass(frozen=True)
class Event:
    id: str
    type: str
    subscription_id: str | None
    customer_id: str | None
    organization_id: str | None
    handled: bool  # one of the event types that can change a subscription


@dataclass(frozen=True)
class NewPrice:
    lookup_key: str
    product_name: str
    unit_amount: int
    interval: str
    currency: str


class BillingProvider(Protocol):
    def prices(self, lookup_keys: list[str]) -> dict[str, str]: ...

    def checkout(
        self,
        *,
        price_id: str,
        customer_id: str | None,
        email: str | None,
        organization_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> str: ...

    def portal(self, *, customer_id: str, return_url: str) -> str: ...

    def subscription(self, subscription_id: str) -> Subscription | None: ...

    def subscriptions_of(self, customer_id: str) -> list[Subscription]: ...

    def verify(self, payload: bytes, signature: str, now: datetime) -> Event: ...

    def create_price(self, price: NewPrice) -> str: ...
