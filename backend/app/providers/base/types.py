"""Normalized base types shared by all providers (D4, D19)."""

from __future__ import annotations

from dataclasses import dataclass, field
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
class AuthorizationRequest:
    state: str
    redirect_uri: str
    code_challenge: str | None = None


@dataclass(frozen=True)
class ConnectResult:
    """Outcome of a completed authorization. ``secrets`` is encrypted before it is stored."""

    secrets: dict[str, Any] = field(repr=False)
    granted_scopes: tuple[str, ...] = ()
    account_label: str | None = None
    token_expires_in_seconds: int | None = None


@dataclass(frozen=True)
class SyncSummary:
    items_synchronized: int
    detail: dict[str, Any] = field(default_factory=dict)
