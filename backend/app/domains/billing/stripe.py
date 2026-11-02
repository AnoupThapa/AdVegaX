"""Stripe, AdVegaX's billing provider (Phase 13, task 13-03, PHASE_13_PLAN §4.1; A32).

One fixed host, ``api.stripe.com``, through the SSRF-safe client; the secret key travels only
in the ``Authorization`` header and is never logged or returned. Requests are form-encoded, as
Stripe's API expects; every ``POST`` carries an ``Idempotency-Key`` so a retried request is
applied once. ``Stripe-Version`` pins the API version when ``STRIPE_API_VERSION`` is set.

Webhooks are verified as Stripe documents: the ``Stripe-Signature`` header holds a timestamp
``t`` and one or more ``v1`` signatures, each the HMAC-SHA256 (hex) of ``"{t}.{raw body}"``
with the endpoint's signing secret; a timestamp older than ``STRIPE_WEBHOOK_TOLERANCE`` is
refused. Only ids are taken from an event: AdVegaX always reads the subscription itself.

Both places Stripe has kept a subscription's period end (on the subscription, or on its item)
and an invoice's subscription (on the invoice, or under ``parent.subscription_details``) are
read, so the answer does not depend on the API version.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from pydantic import SecretStr

from app.domains.billing.provider import (
    BillingError,
    Event,
    InvalidSignature,
    NewPrice,
    Subscription,
)
from app.providers.base.errors import OutboundTimeoutError, ProviderError
from app.providers.http.client import SafeHttpClient

HOST = "api.stripe.com"
GET, POST = "GET", "POST"
HttpFactory = Callable[[], SafeHttpClient]
SUBSCRIPTION_EVENTS = (
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
)
HANDLED = (
    "checkout.session.completed",
    *SUBSCRIPTION_EVENTS,
    "invoice.paid",
    "invoice.payment_failed",
)


def _when(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if isinstance(value, int) else None


def subscription_of(data: dict[str, Any]) -> Subscription:
    items = (data.get("items") or {}).get("data") or []
    first = items[0] if items else {}
    price = first.get("price") or {}
    customer = data.get("customer")
    return Subscription(
        id=str(data["id"]),
        customer_id=str(customer.get("id") if isinstance(customer, dict) else customer),
        status=str(data.get("status") or "incomplete"),
        lookup_key=price.get("lookup_key"),
        current_period_end=_when(data.get("current_period_end"))
        or _when(first.get("current_period_end")),
        cancel_at_period_end=bool(data.get("cancel_at_period_end")),
        organization_id=(data.get("metadata") or {}).get("organization_id"),
    )


def event_of(data: dict[str, Any]) -> Event:
    kind = str(data.get("type") or "")
    obj = (data.get("data") or {}).get("object") or {}
    subscription: Any = None
    organization = (obj.get("metadata") or {}).get("organization_id")
    if kind in SUBSCRIPTION_EVENTS:
        subscription = obj.get("id")
    elif kind == "checkout.session.completed":
        subscription = obj.get("subscription")
        organization = obj.get("client_reference_id") or organization
    elif kind.startswith("invoice."):
        subscription = obj.get("subscription") or (
            ((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription")
        )
    customer = obj.get("customer")
    return Event(
        id=str(data.get("id") or ""),
        type=kind,
        subscription_id=str(subscription) if subscription else None,
        customer_id=str(customer) if isinstance(customer, str) else None,
        organization_id=str(organization) if organization else None,
        handled=kind in HANDLED,
    )


def check_signature(
    payload: bytes, header: str, secret: str, now: datetime, tolerance: timedelta
) -> None:
    parts = [p.split("=", 1) for p in header.split(",") if "=" in p]
    stamps = [v for k, v in parts if k.strip() == "t"]
    signatures = [v for k, v in parts if k.strip() == "v1"]
    if len(stamps) != 1 or not stamps[0].isdigit() or not signatures:
        raise InvalidSignature()
    signed = stamps[0].encode() + b"." + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s.strip()) for s in signatures):
        raise InvalidSignature()
    sent = datetime.fromtimestamp(int(stamps[0]), UTC)
    if abs(now - sent) > tolerance:
        raise InvalidSignature()


class StripeProvider:
    def __init__(
        self,
        secret_key: SecretStr,
        webhook_secret: SecretStr | None,
        api_version: str | None,
        tolerance: timedelta,
        http_factory: HttpFactory,
    ) -> None:
        self._key = secret_key
        self._webhook_secret = webhook_secret
        self._version = api_version
        self._tolerance = tolerance
        self._http = http_factory

    # ------------------------------------------------------------------ transport
    def _call(
        self,
        method: str,
        path: str,
        *,
        form: dict[str, str] | None = None,
        query: list[tuple[str, str]] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"authorization": f"Bearer {self._key.get_secret_value()}"}
        if self._version:
            headers["stripe-version"] = self._version
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key
        url = f"https://{HOST}{path}" + (f"?{urlencode(query)}" if query else "")
        client = self._http()
        try:
            response = client.request(
                method, url, headers=headers, data=form, follow_redirects=False
            )
        except OutboundTimeoutError as exc:
            raise BillingError("billing_timeout") from exc
        except ProviderError as exc:
            raise BillingError("billing_unreachable") from exc
        finally:
            client.close()
        if response.status_code == 404:
            raise BillingError("not_found")
        if response.status_code in (401, 403):
            raise BillingError("billing_key_refused")
        if response.status_code == 429 or response.status_code >= 500:
            raise BillingError("billing_unavailable")
        if response.status_code >= 400:
            raise BillingError("billing_request_refused")
        try:
            answer = json.loads(response.content)
        except ValueError as exc:
            raise BillingError("billing_unexpected_response") from exc
        if not isinstance(answer, dict):
            raise BillingError("billing_unexpected_response")
        return answer

    # ------------------------------------------------------------------ the interface
    def prices(self, lookup_keys: list[str]) -> dict[str, str]:
        query = [("active", "true"), ("limit", "100")] + [("lookup_keys[]", k) for k in lookup_keys]
        answer = self._call(GET, "/v1/prices", query=query)
        return {
            str(p["lookup_key"]): str(p["id"])
            for p in answer.get("data") or []
            if p.get("lookup_key") and p.get("id")
        }

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
    ) -> str:
        form = {
            "mode": "subscription",
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": organization_id,
            "metadata[organization_id]": organization_id,
            "subscription_data[metadata][organization_id]": organization_id,
            "automatic_tax[enabled]": "true",
        }
        if customer_id:
            form["customer"] = customer_id
            form["customer_update[address]"] = "auto"
        elif email:
            form["customer_email"] = email
        answer = self._call(
            POST, "/v1/checkout/sessions", form=form, idempotency_key=idempotency_key
        )
        url = answer.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise BillingError("billing_unexpected_response")
        return url

    def portal(self, *, customer_id: str, return_url: str) -> str:
        answer = self._call(
            POST,
            "/v1/billing_portal/sessions",
            form={"customer": customer_id, "return_url": return_url},
        )
        url = answer.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise BillingError("billing_unexpected_response")
        return url

    def subscription(self, subscription_id: str) -> Subscription | None:
        if not subscription_id.startswith("sub_") or not subscription_id.isascii():
            raise BillingError("billing_request_refused")
        try:
            return subscription_of(self._call(GET, f"/v1/subscriptions/{subscription_id}"))
        except BillingError as exc:
            if exc.code == "not_found":
                return None
            raise

    def subscriptions_of(self, customer_id: str) -> list[Subscription]:
        answer = self._call(
            GET,
            "/v1/subscriptions",
            query=[("customer", customer_id), ("status", "all"), ("limit", "20")],
        )
        return [subscription_of(s) for s in answer.get("data") or []]

    def verify(self, payload: bytes, signature: str, now: datetime) -> Event:
        if self._webhook_secret is None:
            raise InvalidSignature()
        check_signature(
            payload, signature, self._webhook_secret.get_secret_value(), now, self._tolerance
        )
        try:
            data = json.loads(payload)
        except ValueError as exc:
            raise InvalidSignature() from exc
        if not isinstance(data, dict) or not data.get("id"):
            raise InvalidSignature()
        return event_of(data)

    def create_price(self, price: NewPrice) -> str:
        product = self._call(
            POST,
            "/v1/products",
            form={"name": price.product_name},
            idempotency_key=f"product-{price.lookup_key}",
        )
        created = self._call(
            POST,
            "/v1/prices",
            form={
                "product": str(product["id"]),
                "currency": price.currency,
                "unit_amount": str(price.unit_amount),
                "recurring[interval]": price.interval,
                "lookup_key": price.lookup_key,
                "tax_behavior": "inclusive",
            },
            idempotency_key=f"price-{price.lookup_key}",
        )
        return str(created["id"])
