"""Shopify webhook verification and metadata extraction (task 2A-05). No network, no database."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from app.providers.base.errors import InvalidRequestError, InvalidSignatureError
from app.providers.base.types import WebhookDelivery, WebhookKind
from app.providers.shopify.config import ShopifyApp
from app.providers.shopify.signatures import sign_body
from app.providers.shopify.webhooks import parse_webhook

from tests.shopify_sim import CLIENT_ID, CLIENT_SECRET, webhook_request

SHOP = "eve-zone.myshopify.com"
APPS = (ShopifyApp(CLIENT_ID, CLIENT_SECRET, frozenset({"*"})),)


def _parse(topic, payload, *, apps=APPS, **kw):
    headers, body = webhook_request(
        topic, payload, shop=kw.pop("shop", SHOP), webhook_id="w-1", **kw
    )
    return parse_webhook(apps, {k.lower(): v for k, v in headers.items()}, body)


def test_valid_product_webhook_yields_metadata_only():
    delivery = _parse(
        "products/update",
        {
            "id": 788032119674292922,
            "admin_graphql_api_id": "gid://shopify/Product/788032119674292922",
            "title": "Nitrile gloves",
            "updated_at": "2026-10-13T10:00:00-04:00",
        },
        triggered_at="2026-10-13T14:00:01.877041743Z",
    )
    assert delivery == WebhookDelivery(
        webhook_id="w-1",
        topic="products/update",
        account_id=SHOP,
        kind=WebhookKind.OBJECT_CHANGED,
        object_external_id="gid://shopify/Product/788032119674292922",
        object_updated_at=datetime(2026, 10, 13, 14, 0, tzinfo=UTC),
        triggered_at=datetime(2026, 10, 13, 14, 0, 1, 877041, tzinfo=UTC),
    )
    # The dataclass has no payload field at all: personal data cannot travel further.
    assert "title" not in repr(delivery)


def test_order_webhook_does_not_carry_customer_details():
    delivery = _parse(
        "orders/create",
        {
            "id": 820982911946154508,
            "email": "jon@example.com",
            "customer": {"id": 115310627314723954, "email": "jon@example.com", "first_name": "Jon"},
            "shipping_address": {"address1": "123 Street"},
        },
    )
    assert delivery.object_external_id == "gid://shopify/Order/820982911946154508"
    assert "example.com" not in repr(delivery) and "Street" not in repr(delivery)


@pytest.mark.parametrize(
    ("topic", "kind"),
    [
        ("app/uninstalled", WebhookKind.APP_UNINSTALLED),
        ("customers/data_request", WebhookKind.PRIVACY_DATA_REQUEST),
        ("customers/redact", WebhookKind.PRIVACY_CUSTOMER_REDACT),
        ("shop/redact", WebhookKind.PRIVACY_SHOP_REDACT),
        ("inventory_levels/update", WebhookKind.OBJECT_CHANGED),
        ("refunds/create", WebhookKind.OBJECT_CHANGED),
        ("carts/update", WebhookKind.UNHANDLED),
    ],
)
def test_topics_are_classified(topic, kind):
    assert _parse(topic, {}).kind is kind


def test_customer_privacy_request_keeps_only_the_platform_customer_id():
    delivery = _parse(
        "customers/redact",
        {
            "shop_id": 954889,
            "shop_domain": SHOP,
            "customer": {"id": 191167, "email": "john@example.com", "phone": "555-625-1199"},
            "orders_to_redact": [299938, 280263],
        },
    )
    assert delivery.object_external_id == "191167"
    assert "john@" not in repr(delivery) and "555" not in repr(delivery)


def test_shop_redact_has_no_object():
    delivery = _parse("shop/redact", {"shop_id": 954889, "shop_domain": SHOP})
    assert delivery.kind is WebhookKind.PRIVACY_SHOP_REDACT
    assert delivery.object_external_id is None


# ------------------------------------------------------------------ signature
def test_wrong_secret_is_refused():
    with pytest.raises(InvalidSignatureError):
        _parse("products/update", {"id": 1}, secret="another-secret-0123456789")


def test_tampered_body_is_refused():
    headers, body = webhook_request("products/update", {"id": 1}, shop=SHOP, webhook_id="w")
    with pytest.raises(InvalidSignatureError):
        parse_webhook(APPS, {k.lower(): v for k, v in headers.items()}, body.replace(b"1", b"2"))


@pytest.mark.parametrize("value", [None, "", "not base64!", "AAAA"])
def test_missing_or_malformed_signature_is_refused(value):
    headers, body = webhook_request("products/update", {"id": 1}, shop=SHOP, webhook_id="w")
    lower = {k.lower(): v for k, v in headers.items()}
    if value is None:
        del lower["x-shopify-hmac-sha256"]
    else:
        lower["x-shopify-hmac-sha256"] = value
    with pytest.raises(InvalidSignatureError):
        parse_webhook(APPS, lower, body)


@pytest.mark.parametrize("shop", ["", "evil.example.com", "eve-zone.myshopify.com.attacker.io"])
def test_invalid_shop_header_is_refused_before_verification(shop):
    with pytest.raises(InvalidSignatureError):
        _parse("products/update", {"id": 1}, shop=shop)


def test_store_specific_app_secret_is_used():
    apps = (
        ShopifyApp("merchant-app", "merchant-secret-0123456789", frozenset({SHOP})),
        ShopifyApp(CLIENT_ID, CLIENT_SECRET, frozenset({"*"})),
    )
    assert _parse("products/update", {"id": 1}, apps=apps, secret="merchant-secret-0123456789")
    # A store with no app at all cannot be verified.
    only_merchant = apps[:1]
    with pytest.raises(InvalidSignatureError):
        _parse("products/update", {"id": 1}, apps=only_merchant, shop="other.myshopify.com")


# ------------------------------------------------------------------ signed but malformed
def _signed(body: bytes, **headers: str):
    base = {
        "x-shopify-shop-domain": SHOP,
        "x-shopify-topic": "products/update",
        "x-shopify-webhook-id": "w",
        "x-shopify-hmac-sha256": sign_body(body, CLIENT_SECRET),
    }
    base.update(headers)
    return parse_webhook(APPS, base, body)


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (b"not json", {}),
        (b"[1, 2]", {}),
        (b"{}", {"x-shopify-topic": ""}),
        (b"{}", {"x-shopify-webhook-id": ""}),
        (b"{}", {"x-shopify-webhook-id": "x" * 300}),
        (json.dumps({"shop_domain": "other.myshopify.com"}).encode(), {}),
    ],
)
def test_signed_but_malformed_delivery_is_a_bad_request(body, headers):
    with pytest.raises(InvalidRequestError) as caught:
        _signed(body, **headers)
    assert not isinstance(caught.value, InvalidSignatureError)


def test_unparseable_timestamps_become_unknown():
    delivery = _signed(
        json.dumps({"id": True, "updated_at": "yesterday"}).encode(),
        **{"x-shopify-triggered-at": "2026-10-13T10:00:00"},  # no time zone
    )
    assert delivery.object_external_id is None
    assert delivery.object_updated_at is None and delivery.triggered_at is None
