"""Explicit provider capability declarations (A2, A10)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.providers.base.availability import Availability


class Capability(StrEnum):
    WEBHOOKS = "webhooks"
    PRODUCT_COST = "product_cost"
    INVENTORY = "inventory"
    REFUND_LINES = "refund_lines"
    PRESENTMENT_CURRENCY = "presentment_currency"
    VALIDATE_ONLY = "validate_only"
    CREATE_CAMPAIGN = "create_campaign"
    ECOMMERCE_EVENTS = "ecommerce_events"
    TOKEN_REVOCATION = "token_revocation"  # noqa: S105 - capability name
    PKCE = "pkce"
    TOKEN_REFRESH = "token_refresh"  # noqa: S105 - capability name
    BULK_IMPORT = "bulk_import"  # catalogue and order history through bulk exports (2A-06)
    PAGED_IMPORT = "paged_import"  # catalogue and order history read page by page (2B-02)
    APP_INSTALL = "app_install"  # the platform can start the connection (e.g. Shopify install)


@dataclass(frozen=True)
class ProviderCapabilities:
    supported: frozenset[Capability]

    def supports(self, capability: Capability) -> bool:
        return capability in self.supported

    def availability_of(self, capability: Capability) -> Availability:
        """What the core should report for data that depends on ``capability``."""
        return (
            Availability.NOT_SYNCHRONIZED if self.supports(capability) else Availability.UNSUPPORTED
        )

    def as_dict(self) -> dict[str, bool]:
        return {c.value: c in self.supported for c in Capability}

    def to_json(self) -> dict[str, list[str]]:
        return {"supported": sorted(c.value for c in self.supported)}
