"""Shop domain validation (verified 2026-10-13, PHASE_02A_PLAN §4.1).

Shopify's documented pattern ``^[a-zA-Z0-9][a-zA-Z0-9-]*\\.myshopify\\.com$`` is anchored at
both ends so that values such as ``shop.myshopify.com.attacker.example`` are refused. AdVegaX
also accepts a bare store name (``eve-zone``) and a pasted admin/URL form, normalizing them to
``eve-zone.myshopify.com`` before validation.
"""

from __future__ import annotations

import re

_SHOP = re.compile(r"^[a-z0-9][a-z0-9\-]*\.myshopify\.com$")
_NAME = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
MAX_LENGTH = 255


class ShopDomainError(ValueError):
    pass


def is_valid_shop(value: str) -> bool:
    return len(value) <= MAX_LENGTH and _SHOP.fullmatch(value) is not None


def normalize_shop(value: str) -> str:
    """Return ``name.myshopify.com`` or raise ``ShopDomainError``.

    Accepts ``Name``, ``name.myshopify.com``, ``https://name.myshopify.com/admin`` (trailing
    path ignored). Anything else — other domains, credentials, ports, IPs — is refused.
    """
    text = value.strip().lower()
    if not text or len(text) > MAX_LENGTH:
        raise ShopDomainError()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.split("/", 1)[0]
    if any(ch in text for ch in "@:?#\\ "):
        raise ShopDomainError()
    if _NAME.fullmatch(text):
        text = f"{text}.myshopify.com"
    if not is_valid_shop(text):
        raise ShopDomainError()
    return text
