"""Shopify webhook verification and metadata extraction (task 2A-05, PHASE_02A_PLAN §7).

Verified against shopify.dev on 2026-10-13:

* The signature is a base64 HMAC-SHA256 of the **raw** request body with the app's client
  secret, in ``X-Shopify-Hmac-Sha256``; it is checked before the body is parsed.
* Headers: ``X-Shopify-Topic``, ``X-Shopify-Shop-Domain``, ``X-Shopify-Webhook-Id`` (the same
  across retries — the de-duplication key), ``X-Shopify-Triggered-At``.
* The three mandatory privacy topics (``customers/data_request``, ``customers/redact``,
  ``shop/redact``) use the same signature; an invalid signature must be answered with 401.

Only metadata leaves this module: the payload (which can contain customer names, emails and
addresses) is parsed for ids and timestamps and then dropped (Q8).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.providers.base.errors import InvalidRequestError, InvalidSignatureError
from app.providers.base.types import WebhookDelivery, WebhookKind
from app.providers.shopify.config import ShopifyApp
from app.providers.shopify.shops import is_valid_shop
from app.providers.shopify.signatures import verify_body

HMAC_HEADER = "x-shopify-hmac-sha256"
TOPIC_HEADER = "x-shopify-topic"
SHOP_HEADER = "x-shopify-shop-domain"
WEBHOOK_ID_HEADER = "x-shopify-webhook-id"
TRIGGERED_AT_HEADER = "x-shopify-triggered-at"

_MAX_ID = 255

# Topics AdVegaX subscribes to (read-only data it imports) and what each means to the core.
TOPIC_KINDS: Mapping[str, WebhookKind] = {
    "app/uninstalled": WebhookKind.APP_UNINSTALLED,
    "customers/data_request": WebhookKind.PRIVACY_DATA_REQUEST,
    "customers/redact": WebhookKind.PRIVACY_CUSTOMER_REDACT,
    "shop/redact": WebhookKind.PRIVACY_SHOP_REDACT,
    "shop/update": WebhookKind.OBJECT_CHANGED,
    "products/create": WebhookKind.OBJECT_CHANGED,
    "products/update": WebhookKind.OBJECT_CHANGED,
    "products/delete": WebhookKind.OBJECT_CHANGED,
    "inventory_levels/update": WebhookKind.OBJECT_CHANGED,
    "orders/create": WebhookKind.OBJECT_CHANGED,
    "orders/updated": WebhookKind.OBJECT_CHANGED,
    "orders/cancelled": WebhookKind.OBJECT_CHANGED,
    "orders/delete": WebhookKind.OBJECT_CHANGED,
    "refunds/create": WebhookKind.OBJECT_CHANGED,
    "bulk_operations/finish": WebhookKind.OBJECT_CHANGED,
}


def _apps_for(apps: tuple[ShopifyApp, ...], shop: str) -> list[ShopifyApp]:
    """Apps that may have signed a webhook for ``shop``: explicit entries first."""
    explicit = [a for a in apps if shop in a.shops]
    return explicit + [a for a in apps if "*" in a.shops and a not in explicit]


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _short(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    return text if 0 < len(text) <= _MAX_ID else None


def _object_id(kind: WebhookKind, payload: dict[str, Any]) -> str | None:
    if kind in (WebhookKind.PRIVACY_DATA_REQUEST, WebhookKind.PRIVACY_CUSTOMER_REDACT):
        customer = payload.get("customer")
        return _short(customer.get("id")) if isinstance(customer, dict) else None
    if kind is WebhookKind.OBJECT_CHANGED:
        return _short(payload.get("admin_graphql_api_id")) or _short(payload.get("id"))
    return None


def parse_webhook(
    apps: tuple[ShopifyApp, ...], headers: Mapping[str, str], body: bytes
) -> WebhookDelivery:
    shop = headers.get(SHOP_HEADER, "").strip().lower()
    if not is_valid_shop(shop):
        raise InvalidSignatureError()  # no store → no secret to verify with
    signature = headers.get(HMAC_HEADER)
    if not any(verify_body(body, signature, app.client_secret) for app in _apps_for(apps, shop)):
        raise InvalidSignatureError()

    # Signed by Shopify from here on; malformed content is a 400, not a 401.
    topic = headers.get(TOPIC_HEADER, "").strip().lower()
    webhook_id = headers.get(WEBHOOK_ID_HEADER, "").strip()
    if not topic or len(topic) > 128 or not webhook_id or len(webhook_id) > _MAX_ID:
        raise InvalidRequestError("webhook_headers_invalid")
    try:
        payload = json.loads(body) if body else {}
    except (ValueError, UnicodeDecodeError):
        raise InvalidRequestError("webhook_body_invalid") from None
    if not isinstance(payload, dict):
        raise InvalidRequestError("webhook_body_invalid")

    kind = TOPIC_KINDS.get(topic, WebhookKind.UNHANDLED)
    body_shop = payload.get("shop_domain")
    if body_shop is not None and str(body_shop).strip().lower() != shop:
        raise InvalidRequestError("webhook_shop_mismatch")
    return WebhookDelivery(
        webhook_id=webhook_id,
        topic=topic,
        account_id=shop,
        kind=kind,
        object_external_id=_object_id(kind, payload),
        object_updated_at=_timestamp(payload.get("updated_at")),
        triggered_at=_timestamp(headers.get(TRIGGERED_AT_HEADER)),
    )
