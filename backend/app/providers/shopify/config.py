"""Shopify app configuration (PHASE_02A_PLAN §6, §7).

Custom-distribution apps serve a single merchant (one store, or stores of one Plus
organization), so AdVegaX may hold several Shopify apps. Each entry says which store domains it
serves; ``"*"`` means any store (a development app, or later the public app). The client secret
comes from the environment / secret store only and is never logged (``repr`` hides it).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.providers.shopify.shops import ShopDomainError, normalize_shop


class ShopifyConfigError(ValueError):
    """``SHOPIFY_APPS`` is malformed. The message never contains a secret."""


@dataclass(frozen=True)
class ShopifyApp:
    client_id: str
    client_secret: str = field(repr=False)
    shops: frozenset[str] = frozenset({"*"})

    def serves(self, shop: str) -> bool:
        return "*" in self.shops or shop in self.shops


def parse_apps(raw: str) -> tuple[ShopifyApp, ...]:
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        raise ShopifyConfigError("SHOPIFY_APPS must be a JSON list") from None
    if not isinstance(entries, list) or not entries:
        raise ShopifyConfigError("SHOPIFY_APPS must be a non-empty JSON list")
    apps: list[ShopifyApp] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ShopifyConfigError(f"SHOPIFY_APPS[{index}] must be an object")
        client_id, secret = entry.get("client_id"), entry.get("client_secret")
        if not isinstance(client_id, str) or not client_id.strip():
            raise ShopifyConfigError(f"SHOPIFY_APPS[{index}].client_id is required")
        if not isinstance(secret, str) or len(secret) < 16:
            raise ShopifyConfigError(f"SHOPIFY_APPS[{index}].client_secret is missing or too short")
        if client_id in seen:
            raise ShopifyConfigError(f"SHOPIFY_APPS[{index}].client_id is duplicated")
        seen.add(client_id)
        shops_raw = entry.get("shops", ["*"])
        if not isinstance(shops_raw, list) or not shops_raw:
            raise ShopifyConfigError(f"SHOPIFY_APPS[{index}].shops must be a non-empty list")
        shops: set[str] = set()
        for shop in shops_raw:
            if shop == "*":
                shops.add("*")
                continue
            try:
                shops.add(normalize_shop(str(shop)))
            except ShopDomainError:
                raise ShopifyConfigError(
                    f"SHOPIFY_APPS[{index}].shops contains an invalid store domain"
                ) from None
        apps.append(ShopifyApp(client_id.strip(), secret, frozenset(shops)))
    return tuple(apps)


def app_for_shop(apps: tuple[ShopifyApp, ...], shop: str) -> ShopifyApp | None:
    """The app that serves ``shop``: an explicit store entry wins over a ``"*"`` app."""
    explicit = [a for a in apps if shop in a.shops]
    if explicit:
        return explicit[0]
    wildcard = [a for a in apps if "*" in a.shops]
    return wildcard[0] if wildcard else None
