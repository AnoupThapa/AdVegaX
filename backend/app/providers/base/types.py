"""Normalized base types shared by all providers (D4, D19)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
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
    # Phase 3: a plain message key when the resource cannot be linked (e.g. ``manager_account``,
    # ``account_cancelled``); the groups it sits in, for display (e.g. "Agency > Retail"); and an
    # opaque, non-secret value the provider needs to reach it again (Google Ads: the manager
    # account to sign in through). Never secrets.
    unavailable_reason: str | None = None
    group_path: str | None = None
    access_hint: str | None = None


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
    # Where the platform posts credentials server to server (``Capability.KEY_DELIVERY``);
    # ``redirect_uri`` is then only the browser's way back to AdVegaX.
    delivery_uri: str | None = None


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
    # True when the same platform account may be connected in several organizations (e.g. one
    # Google sign-in used by a business and its agency, Q-3-11): the id then only recognises a
    # reconnect within the organization and never blocks another organization.
    account_per_organization: bool = False


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


# ---------------------------------------------------------------- commerce import (2A-06)
class BulkKind(StrEnum):
    """What a bulk export contains."""

    CATALOGUE = "catalogue"  # products → variants (with inventory and unit cost)
    ORDERS = "orders"  # orders → line items, sales agreements → sales; refunds


class BulkStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class BulkOperationState:
    """State of a platform bulk export. ``result_url`` is a signed, time-limited download link:
    treat it like a secret — never log or store it (PHASE_02A_PLAN §20 item 12)."""

    status: BulkStatus
    result_url: str | None = field(default=None, repr=False)
    error_code: str | None = None
    object_count: int | None = None


@dataclass(frozen=True)
class CommerceProductRecord:
    external_id: str
    title: str
    status: str  # one of the core PRODUCT_STATUSES
    handle: str | None = None
    product_type: str | None = None
    vendor: str | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class CommerceVariantRecord:
    external_id: str
    product_external_id: str
    title: str | None = None
    sku: str | None = None
    price: Decimal | None = None
    inventory_item_id: str | None = None
    inventory_tracked: bool | None = None
    inventory_available: int | None = None  # None when not tracked — never 0 by default
    unit_cost: Decimal | None = None  # None = the platform has no cost (or hides it)
    cost_currency: str | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class CommerceOrderRecord:
    external_id: str
    currency: str
    ordered_at: datetime
    order_number: str | None = None
    cancelled_at: datetime | None = None
    financial_status: str | None = None
    discount_amount: Decimal | None = None
    shipping_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    refund_amount: Decimal | None = None
    total_amount: Decimal | None = None
    updated_at: datetime | None = None
    # Kept but not counted in the figures (2B): "status" (e.g. pending payment, cancelled) or
    # "other_currency". None = counted.
    excluded_reason: str | None = None


@dataclass(frozen=True)
class CommerceOrderLineRecord:
    external_id: str
    order_external_id: str
    quantity: int
    variant_external_id: str | None = None
    title: str | None = None
    sku: str | None = None
    unit_price: Decimal | None = None
    # Platforms that record cost on the order itself (WooCommerce COGS, 2B-05): the unit cost
    # at the time of sale, or None when the platform recorded none — then the line has no
    # cost (never a later product cost, never 0).
    unit_cost: Decimal | None = None
    cost_from_platform: bool = False


@dataclass(frozen=True)
class CommerceSaleRecord:
    """One sale or reversal with its own date (a platform "sales agreement" line)."""

    external_id: str
    agreement_external_id: str
    order_external_id: str
    happened_at: datetime
    agreement_reason: str  # order | order_edit | refund | return | other
    action: str  # order | return | update | other
    line_type: str  # one of the core SALE_LINE_TYPES
    amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    currency: str
    quantity: int | None = None
    line_item_external_id: str | None = None


@dataclass(frozen=True)
class CommerceRefundRecord:
    external_id: str
    order_external_id: str
    processed_at: datetime
    currency: str
    total_amount: Decimal | None = None


CommerceRecord = (
    CommerceProductRecord
    | CommerceVariantRecord
    | CommerceOrderRecord
    | CommerceOrderLineRecord
    | CommerceSaleRecord
    | CommerceRefundRecord
)


# ---------------------------------------------------------------- incremental sync (2A-07)
class ChangedObject(StrEnum):
    """What an "object changed" webhook points at, once mapped by the provider."""

    PRODUCT = "product"
    ORDER = "order"
    INVENTORY_ITEM = "inventory_item"  # resolved by the core to its product
    NONE = "none"  # nothing to fetch (e.g. shop or bulk-operation notices)


@dataclass(frozen=True)
class WebhookTarget:
    object: ChangedObject
    deleted: bool = False  # the platform deleted the object: remove/mark it, fetch nothing


@dataclass(frozen=True)
class FetchResult:
    """One object fetched by id, as normalized records (same shapes as a bulk export).

    ``found`` is False when the platform no longer has it; ``complete`` is False when a nested
    list was longer than one request allows — the core then reconciles the store instead.
    """

    records: tuple[CommerceRecord, ...] = ()
    found: bool = True
    complete: bool = True


# ---------------------------------------------------------------- paged import (2B-02)
@dataclass(frozen=True)
class CommercePage:
    """One page of a paged import. ``next_cursor`` is the provider's opaque position (None =
    this kind is complete); ``progress`` is an optional 0-100 estimate within the kind."""

    records: tuple[CommerceRecord, ...]
    next_cursor: str | None = None
    progress: int | None = None


@dataclass(frozen=True)
class StoreHealth:
    """Configuration of a (self-hosted) store, checked daily (2B-06). ``warnings`` are plain
    codes for the web app, most important first; empty when nothing needs the merchant."""

    platform_version: str | None = None
    site_url: str | None = None
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------- advertising (Phase 3)
class AdLevel(StrEnum):
    """Levels of daily performance, stored as reported and never added into each other."""

    ACCOUNT = "account"
    CAMPAIGN = "campaign"
    AD_GROUP = "ad_group"  # Google ad group / Meta ad set
    AD = "ad"


class AdEntityStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"  # Meta
    REMOVED = "removed"


@dataclass(frozen=True)
class AdAccountRef:
    """How a provider reaches a linked ad account: its id and the resource's ``access_hint``."""

    external_id: str
    access_hint: str | None = None


@dataclass(frozen=True)
class AdAccountState:
    """The platform's view of an ad account (name, currency, time zone, status)."""

    external_id: str
    name: str | None
    currency: str
    timezone: str
    platform_status: str  # active | not_enabled | cancelled | suspended | closed


@dataclass(frozen=True)
class AdBudgetRecord:
    external_id: str
    level: str  # campaign | ad_group
    period: str  # daily | lifetime
    amount: Decimal | None  # account currency; None when the platform gives none (never 0)
    shared: bool = False
    name: str | None = None


@dataclass(frozen=True)
class AdCampaignRecord:
    external_id: str
    name: str
    status: AdEntityStatus
    platform_type: str | None = None
    bidding_strategy_type: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    budget_external_id: str | None = None
    extensions: Mapping[str, Any] | None = None  # display only


@dataclass(frozen=True)
class AdGroupRecord:
    external_id: str
    campaign_external_id: str
    name: str
    status: AdEntityStatus
    platform_type: str | None = None
    budget_external_id: str | None = None
    extensions: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class AdRecord:
    external_id: str
    ad_group_external_id: str
    status: AdEntityStatus
    name: str | None = None
    platform_type: str | None = None
    extensions: Mapping[str, Any] | None = None


AdStructureRecord = AdBudgetRecord | AdCampaignRecord | AdGroupRecord | AdRecord


@dataclass(frozen=True)
class AdPerformanceRecord:
    """One entity's figures for one day (in the ad account's time zone), as reported.

    ``entity_external_id`` is None at the account level. Measures the platform did not provide
    are None, never 0 (A10). Money is exact, in the account currency.
    """

    level: AdLevel
    day: date
    entity_external_id: str | None = None
    campaign_external_id: str | None = None
    ad_group_external_id: str | None = None
    impressions: int | None = None
    clicks: int | None = None
    cost: Decimal | None = None
    conversions: Decimal | None = None
    conversion_value: Decimal | None = None
