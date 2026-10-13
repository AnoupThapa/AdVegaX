"""Normalized base types shared by all providers (D4, D19)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class ProviderCategory(StrEnum):
    COMMERCE = "commerce"
    ADVERTISING = "advertising"
    ANALYTICS = "analytics"


class AuthScheme(StrEnum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    APP_KEY = "app_key"


class ResourceKind(StrEnum):
    STORE = "store"
    AD_ACCOUNT = "ad_account"
    ANALYTICS_PROPERTY = "analytics_property"
    BUSINESS_ASSET = "business_asset"


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("Money.amount must be a Decimal")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError("Money.currency must be an ISO 4217 code")


@dataclass(frozen=True)
class ResourceDescriptor:
    kind: ResourceKind
    external_id: str
    display_name: str | None = None
    currency: str | None = None
    timezone: str | None = None


@dataclass(frozen=True)
class PreparedConnect:
    """Validated, normalized connect parameters (e.g. a Shopify shop domain).

    ``account_id`` identifies the single platform account the connection will reach, when the
    platform has that notion; the core uses it to enforce one live connection per account
    across organizations *before* any token exchange (Q6, PHASE_02A_PLAN §6.4).
    """

    params: dict[str, str] = field(default_factory=dict)
    account_id: str | None = None


@dataclass(frozen=True)
class AuthorizationRequest:
    state: str
    redirect_uri: str
    code_challenge: str | None = None
    provider_params: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectResult:
    """Outcome of a completed authorization. ``secrets`` is encrypted before it is stored."""

    secrets: dict[str, Any] = field(repr=False)
    granted_scopes: tuple[str, ...] = ()
    account_label: str | None = None
    token_expires_in_seconds: int | None = None
    refresh_expires_in_seconds: int | None = None
    # Stable platform account identifier (e.g. shop domain); see ``PreparedConnect``.
    external_account_id: str | None = None


@dataclass(frozen=True)
class SyncSummary:
    items_synchronized: int
    detail: dict[str, Any] = field(default_factory=dict)


class WebhookKind(StrEnum):
    """What a verified platform webhook means to the core (PHASE_02A_PLAN §7)."""

    OBJECT_CHANGED = "object_changed"  # "object X changed": fetch it by id (2A-07)
    APP_UNINSTALLED = "app_uninstalled"  # access ended: revoke the connection now
    PRIVACY_DATA_REQUEST = "privacy_data_request"
    PRIVACY_CUSTOMER_REDACT = "privacy_customer_redact"
    PRIVACY_SHOP_REDACT = "privacy_shop_redact"
    UNHANDLED = "unhandled"  # verified but not a topic AdVegaX subscribes to


PRIVACY_KINDS = frozenset(
    {
        WebhookKind.PRIVACY_DATA_REQUEST,
        WebhookKind.PRIVACY_CUSTOMER_REDACT,
        WebhookKind.PRIVACY_SHOP_REDACT,
    }
)


@dataclass(frozen=True)
class WebhookDelivery:
    """Metadata of a **verified** webhook. Deliberately has no payload field: the body is
    discarded after verification so customer personal data is never stored (Q8).

    ``object_external_id`` is the platform's id of the changed object (or, for a customer
    privacy request, the platform's customer id — a pseudonymous id, never an email or name).
    """

    webhook_id: str
    topic: str
    account_id: str
    kind: WebhookKind
    object_external_id: str | None = None
    object_updated_at: datetime | None = None
    triggered_at: datetime | None = None
