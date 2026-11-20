"""A Stripe simulator for tests (Phase 13, task 13-03, PHASE_13_PLAN §8).

Answers like Stripe's REST API for the calls AdVegaX makes (prices by lookup key, products,
prices, Checkout Sessions, customer portal sessions, subscriptions), form-encoded requests and
JSON answers, served behind the real ``SafeHttpClient`` with ``httpx.MockTransport`` — so the
real ``StripeProvider`` is what the tests exercise. Webhook events are signed as Stripe signs
them (``t=…,v1=HMAC-SHA256("{t}.{body}")``). No network: CI never calls Stripe.

The simulator also plays the customer: ``pay(session)`` completes a Checkout Session (a
customer and an active subscription), and ``change``/``fail``/``pay_again``/``cancel``/``end``
move a subscription the way the portal and Stripe's retries would.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx
from app.domains.billing.stripe import StripeProvider
from app.providers.http.client import OutboundPolicy, SafeHttpClient
from pydantic import SecretStr

PUBLIC_IP = "54.187.174.169"
POLICY = OutboundPolicy(
    connect_timeout=1, read_timeout=1, max_response_bytes=5_000_000, max_redirects=0
)
SECRET_KEY = "sk_test_simulated"
WEBHOOK_SECRET = "whsec_simulated"
MONTH = 30 * 86_400  # seconds; the simulator's billing period


@dataclass
class StripeSim:
    clock: Any = None  # the test clock; event timestamps and periods follow it
    prices: dict[str, dict[str, Any]] = field(default_factory=dict)
    products: dict[str, dict[str, Any]] = field(default_factory=dict)
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    subscriptions: dict[str, dict[str, Any]] = field(default_factory=dict)
    portals: list[dict[str, Any]] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)
    fail: int | None = None  # HTTP status for every call
    _ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))
    # Stripe's ids are unique everywhere; a run-specific part keeps them unique across runs
    # against the same database (the browser tests' development database keeps its events).
    _run: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    # ------------------------------------------------------------------ plumbing
    def _id(self, prefix: str) -> str:
        return f"{prefix}_sim{self._run}{next(self._ids):04d}"

    def stamp(self) -> int:
        assert self.clock is not None, "give the simulator the test clock"
        return int(self.clock.now().timestamp())

    def http_factory(self) -> SafeHttpClient:
        return SafeHttpClient(
            POLICY,
            resolver=lambda host, port: [PUBLIC_IP],
            transport=httpx.MockTransport(self.handler),
        )

    def provider(self, *, webhook_secret: str | None = WEBHOOK_SECRET) -> StripeProvider:
        from datetime import timedelta

        return StripeProvider(
            SecretStr(SECRET_KEY),
            SecretStr(webhook_secret) if webhook_secret else None,
            "2026-09-30.basil",
            timedelta(minutes=5),
            self.http_factory,
        )

    def calls(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == path]

    # ------------------------------------------------------------------ the API
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("host") != "api.stripe.com":
            return httpx.Response(404)
        if request.headers.get("authorization") != f"Bearer {SECRET_KEY}":
            return _error(401, "invalid_api_key")
        if self.fail is not None:
            return _error(self.fail, "api_error")
        query = parse_qs(request.url.query.decode())
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        path, method = request.url.path, request.method
        keyless = method == "POST" and not request.headers.get("idempotency-key")
        if keyless and path != "/v1/billing_portal/sessions":
            return _error(400, "missing_idempotency_key")
        if (method, path) == ("GET", "/v1/prices"):
            keys = query.get("lookup_keys[]", [])
            data = [p for p in self.prices.values() if p["lookup_key"] in keys and p["active"]]
            return _ok({"object": "list", "data": data, "has_more": False})
        if (method, path) == ("POST", "/v1/products"):
            product = {"id": self._id("prod"), "name": form["name"]}
            self.products[product["id"]] = product
            return _ok(product)
        if (method, path) == ("POST", "/v1/prices"):
            return _ok(self.add_price(form))
        if (method, path) == ("POST", "/v1/checkout/sessions"):
            return self._checkout(form)
        if (method, path) == ("POST", "/v1/billing_portal/sessions"):
            if not any(s["customer"] == form.get("customer") for s in self.subscriptions.values()):
                return _error(400, "resource_missing")
            portal = {
                "id": self._id("bps"),
                "url": f"https://billing.stripe.com/p/session/{form['customer']}",
                **form,
            }
            self.portals.append(portal)
            return _ok(portal)
        if (method, path) == ("GET", "/v1/subscriptions"):
            customer = query.get("customer", [None])[0]
            data = [s for s in self.subscriptions.values() if s["customer"] == customer]
            return _ok({"object": "list", "data": data[::-1], "has_more": False})
        if method == "GET" and path.startswith("/v1/subscriptions/"):
            sub = self.subscriptions.get(path.rsplit("/", 1)[1])
            return _ok(sub) if sub else _error(404, "resource_missing")
        return _error(404, "unknown_path")

    def add_price(self, form: dict[str, str]) -> dict[str, Any]:
        price = {
            "id": self._id("price"),
            "object": "price",
            "active": True,
            "product": form.get("product", "prod_x"),
            "currency": form["currency"],
            "unit_amount": int(form["unit_amount"]),
            "recurring": {"interval": form["recurring[interval]"]},
            "lookup_key": form["lookup_key"],
            "tax_behavior": form.get("tax_behavior"),
        }
        self.prices[price["id"]] = price
        return price

    def seed_prices(self) -> None:
        """Every AdVegaX price, as the setup command would have created them."""
        from app.domains.billing.plans import PLANS

        for plan in PLANS.values():
            for interval in ("month", "year"):
                self.add_price(
                    {
                        "currency": "aud",
                        "unit_amount": str(plan.price(interval)),
                        "recurring[interval]": interval,
                        "lookup_key": plan.lookup_key(interval),
                        "tax_behavior": "inclusive",
                    }
                )

    def price_of(self, lookup_key: str) -> dict[str, Any]:
        return next(p for p in self.prices.values() if p["lookup_key"] == lookup_key)

    def _checkout(self, form: dict[str, str]) -> httpx.Response:
        price = self.prices.get(form.get("line_items[0][price]", ""))
        if price is None or form.get("mode") != "subscription":
            return _error(400, "invalid_request")
        session = {"id": self._id("cs"), "object": "checkout.session", **form}
        session["url"] = f"https://checkout.stripe.com/c/pay/{session['id']}"
        self.sessions[session["id"]] = session
        return _ok(session)

    # ------------------------------------------------------------------ the customer
    def pay(self, session_id: str) -> tuple[bytes, str]:
        """Complete Checkout: a customer (or the existing one) and an active subscription.
        Returns the signed ``checkout.session.completed`` event."""
        session = self.sessions[session_id]
        customer = session.get("customer") or self._id("cus")
        price = self.prices[session["line_items[0][price]"]]
        sub = {
            "id": self._id("sub"),
            "object": "subscription",
            "customer": customer,
            "status": "active",
            "cancel_at_period_end": False,
            "metadata": {"organization_id": session["metadata[organization_id]"]},
            "items": {
                "data": [
                    {
                        "price": {"id": price["id"], "lookup_key": price["lookup_key"]},
                        "current_period_end": self.stamp() + MONTH,
                    }
                ]
            },
        }
        self.subscriptions[sub["id"]] = sub
        obj = {
            "id": session_id,
            "object": "checkout.session",
            "customer": customer,
            "subscription": sub["id"],
            "client_reference_id": session["client_reference_id"],
            "metadata": {"organization_id": session["metadata[organization_id]"]},
        }
        return self.event("checkout.session.completed", obj)

    def latest(self) -> dict[str, Any]:
        return list(self.subscriptions.values())[-1]

    def change(self, sub_id: str, lookup_key: str) -> tuple[bytes, str]:
        price = self.price_of(lookup_key)
        self.subscriptions[sub_id]["items"]["data"][0]["price"] = {
            "id": price["id"],
            "lookup_key": lookup_key,
        }
        return self.updated(sub_id)

    def set(self, sub_id: str, **values: Any) -> tuple[bytes, str]:
        self.subscriptions[sub_id].update(values)
        return self.updated(sub_id)

    def updated(self, sub_id: str) -> tuple[bytes, str]:
        return self.event("customer.subscription.updated", dict(self.subscriptions[sub_id]))

    def fail_payment(self, sub_id: str) -> tuple[bytes, str]:
        sub = self.subscriptions[sub_id]
        sub["status"] = "past_due"
        invoice = {
            "id": self._id("in"),
            "object": "invoice",
            "customer": sub["customer"],
            # Newer API versions keep the subscription under ``parent``.
            "parent": {"subscription_details": {"subscription": sub_id}},
        }
        return self.event("invoice.payment_failed", invoice)

    def pay_again(self, sub_id: str) -> tuple[bytes, str]:
        sub = self.subscriptions[sub_id]
        sub["status"] = "active"
        invoice = {
            "id": self._id("in"),
            "object": "invoice",
            "customer": sub["customer"],
            "subscription": sub_id,
        }
        return self.event("invoice.paid", invoice)

    def end(self, sub_id: str) -> tuple[bytes, str]:
        sub = self.subscriptions[sub_id]
        sub["status"] = "canceled"
        sub["cancel_at_period_end"] = False
        return self.event("customer.subscription.deleted", dict(sub))

    # ------------------------------------------------------------------ webhooks
    def event(
        self, kind: str, obj: dict[str, Any], *, event_id: str | None = None
    ) -> tuple[bytes, str]:
        body = {
            "id": event_id or self._id("evt"),
            "object": "event",
            "type": kind,
            "created": self.stamp(),
            "data": {"object": obj},
        }
        payload = json.dumps(body).encode()
        return payload, self.sign(payload)

    def sign(self, payload: bytes, *, at: int | None = None, secret: str = WEBHOOK_SECRET) -> str:
        t = at if at is not None else self.stamp()
        mac = hmac.new(secret.encode(), str(t).encode() + b"." + payload, hashlib.sha256)
        return f"t={t},v1={mac.hexdigest()}"


def _ok(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=body)


def _error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"type": "invalid_request_error", "code": code}})
