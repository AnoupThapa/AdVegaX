"""WooCommerce provider (Phase 2B, PHASE_02B_PLAN §6). Read-only; self-hosted stores.

Connecting (2B-04):

1. ``prepare_connect`` normalizes the store address (``stores.py``); the store's identity
   (host + path) enforces one live connection per store across organizations.
2. ``authorization_url`` first checks that the address answers with a WooCommerce REST API
   (public WordPress index, ``wc/v3`` namespace), then sends the person to the store's own
   ``/wc-auth/v1/authorize`` page asking for **read** access. ``user_id`` carries AdVegaX's
   single-use connect state; ``callback_url`` is where the store posts the generated key.
3. ``complete_authorization`` receives that posted key (via the core's key-delivery route).
   Only a ``read`` key is accepted, and it is verified **against the store recorded in the
   connect state**: the system status must answer with the key and report WooCommerce
   ``WOOCOMMERCE_MIN_VERSION`` or newer (Q10a). Nothing in the posted body decides which
   address is called.

Keys do not expire and cannot be revoked by AdVegaX with read access (Q-2B-7); disconnecting
deletes AdVegaX's copy and the web app asks the merchant to revoke the key in WooCommerce.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.providers.base.capabilities import Capability, ProviderCapabilities
from app.providers.base.errors import (
    AuthExpiredError,
    InvalidConnectParamsError,
    InvalidRequestError,
    UnsupportedOperationError,
)
from app.providers.base.interfaces import Secrets
from app.providers.base.types import (
    AuthorizationRequest,
    AuthScheme,
    BulkKind,
    ChangedObject,
    CommercePage,
    CommerceRecord,
    ConnectResult,
    FetchResult,
    PreparedConnect,
    ProviderCategory,
    ResourceDescriptor,
    ResourceKind,
    SyncSummary,
    WebhookDelivery,
    WebhookTarget,
)
from app.providers.woocommerce import mapping
from app.providers.woocommerce.client import (
    HttpFactory,
    UnexpectedResponseError,
    WooClient,
    WooCommerceApiNotFoundError,
)
from app.providers.woocommerce.stores import StoreAddress, normalize_store_url

logger = logging.getLogger("advegax.woocommerce")
PER_PAGE = 100
VARIABLE_PER_PAGE = 20  # variable products per step while reading their variations

READ_SCOPE = "read"
_KEY = re.compile(r"^ck_[A-Za-z0-9]{20,64}$")
_SECRET = re.compile(r"^cs_[A-Za-z0-9]{20,64}$")
_VERSION = re.compile(r"^(\d{1,3})\.(\d{1,3})(?:\.(\d{1,4}))?")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class NotReadOnlyError(InvalidRequestError):
    """The store generated a key with more than read access; AdVegaX never stores one."""

    code = "not_read_only"


class WooCommerceTooOldError(InvalidRequestError):
    """The store runs a WooCommerce version older than the supported minimum (Q10a)."""

    code = "woocommerce_too_old"


class WooCommerceProvider:
    code = "woocommerce"
    display_name = "WooCommerce"
    category = ProviderCategory.COMMERCE
    auth_scheme = AuthScheme.API_KEY
    capabilities = ProviderCapabilities(
        frozenset(
            {
                Capability.KEY_DELIVERY,
                Capability.PAGED_IMPORT,
                Capability.PRODUCT_COST,
                Capability.INVENTORY,
                Capability.REFUND_LINES,
            }
        )
    )
    test_only = False
    rate_limit = (2.0, 4)  # per connection = per store: gentle on small shared hosts

    def __init__(
        self,
        *,
        http_factory: HttpFactory,
        app_name: str = "AdVegaX",
        min_version: tuple[int, int] = (9, 0),
    ) -> None:
        self._http_factory = http_factory
        self._app_name = app_name
        self._min_version = min_version

    # ------------------------------------------------------------------ connect
    def prepare_connect(self, params: Mapping[str, str]) -> PreparedConnect:
        if set(params) != {"store_url"}:
            raise InvalidConnectParamsError()
        store = normalize_store_url(params["store_url"])
        return PreparedConnect(params={"store_url": store.base_url}, account_id=store.account_id)

    def authorization_url(self, request: AuthorizationRequest) -> str:
        if request.delivery_uri is None:
            raise InvalidConnectParamsError("delivery_uri_missing")
        store = self._store(request.provider_params)
        index = WooClient(self._http_factory, store).index()
        namespaces = index.get("namespaces")
        if not isinstance(namespaces, list) or "wc/v3" not in namespaces:
            raise WooCommerceApiNotFoundError()
        query = urlencode(
            {
                "app_name": self._app_name,
                "scope": READ_SCOPE,
                "user_id": request.state,
                "return_url": request.redirect_uri,
                "callback_url": request.delivery_uri,
            }
        )
        return f"{store.base_url}/wc-auth/v1/authorize?{query}"

    def complete_authorization(
        self,
        params: Mapping[str, str],
        *,
        redirect_uri: str,  # noqa: ARG002 - provider contract
        code_verifier: str | None,  # noqa: ARG002 - not used by key delivery
        provider_params: Mapping[str, str],
    ) -> ConnectResult:
        """Accept a delivered key only if it is read-only and works on the expected store."""
        key, secret = params.get("consumer_key", ""), params.get("consumer_secret", "")
        if not _KEY.fullmatch(key) or not _SECRET.fullmatch(secret):
            raise InvalidRequestError("invalid_key")
        if params.get("key_permissions") != READ_SCOPE:
            raise NotReadOnlyError()
        store = self._store(provider_params)
        client = WooClient(self._http_factory, store, consumer_key=key, consumer_secret=secret)
        status = _object(client.get("/system_status").data)
        environment = _object(status.get("environment"))
        if not self._supported(environment.get("version")):
            raise WooCommerceTooOldError()
        index = client.index()
        name = index.get("name")
        key_id = params.get("key_id", "")
        return ConnectResult(
            secrets={
                "store_url": store.base_url,
                "consumer_key": key,
                "consumer_secret": secret,
                "key_id": key_id if key_id.isdigit() and len(key_id) <= 20 else None,
            },
            granted_scopes=(READ_SCOPE,),
            account_label=name[:255] if isinstance(name, str) and name.strip() else store.host,
            external_account_id=store.account_id,
        )

    def verify_install(self, params: Mapping[str, str]) -> str:  # noqa: ARG002
        raise UnsupportedOperationError()

    # ------------------------------------------------------------------ discovery
    def discover_resources(self, secrets: Secrets) -> list[ResourceDescriptor]:
        store, client = self._client(secrets)
        status = _object(client.get("/system_status").data)
        settings = _object(status.get("settings"))
        currency = settings.get("currency")
        index = client.index()
        name = index.get("name")
        return [
            ResourceDescriptor(
                kind=ResourceKind.STORE,
                external_id=store.account_id,
                display_name=name[:255] if isinstance(name, str) and name.strip() else store.host,
                currency=currency
                if isinstance(currency, str) and _CURRENCY.fullmatch(currency)
                else None,
                timezone=store_timezone(index.get("timezone_string"), index.get("gmt_offset")),
            )
        ]

    def sync_resource(self, secrets: Secrets, resource: ResourceDescriptor) -> SyncSummary:  # noqa: ARG002
        # Stores are imported page by page, driven by the core (paged import, 2B-05).
        raise UnsupportedOperationError()

    def revoke(self, secrets: Secrets) -> None:  # noqa: ARG002
        # A read-only key cannot delete itself (Q-2B-7); the merchant revokes it in WooCommerce.
        raise UnsupportedOperationError()

    def refresh_credentials(self, secrets: Secrets) -> ConnectResult:  # noqa: ARG002
        raise UnsupportedOperationError()  # keys do not expire

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookDelivery:  # noqa: ARG002
        raise UnsupportedOperationError()  # no webhooks in 2B (Q-2B-3)

    # ------------------------------------------------------------------ commerce
    def history_limit(self, granted_scopes: tuple[str, ...]) -> timedelta | None:  # noqa: ARG002
        return None  # WooCommerce allows the whole history; the core applies 13 months

    def read_page(
        self,
        secrets: Secrets,
        kind: BulkKind,
        cursor: str | None,
        *,
        created_since: datetime | None = None,
        updated_since: datetime | None = None,
    ) -> CommercePage:
        """One page of the paged import (2B-05). The cursor walks:

        * catalogue: products (all types, id order) → for each variable product (20 per step)
          its variations;
        * orders: orders created since ``created_since`` → refunds created since then.

        ``updated_since`` (the 15-minute and hourly checks) limits products, variable products
        and orders to those modified since then, and refunds to those created since then.
        The store's currency is read once (system status) and travels in the cursor.
        """
        _, client = self._client(secrets)
        state = _decode(cursor)
        if "c" not in state:
            settings = _object(_object(client.get("/system_status").data).get("settings"))
            currency = settings.get("currency")
            if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
                raise UnexpectedResponseError()
            first = "p" if kind is BulkKind.CATALOGUE else "o"
            state = {"s": first, "pg": 1, "c": currency}
        currency = str(state["c"])
        modified = _when(updated_since)
        stage = state.get("s")
        if stage == "p":
            params = _filters(
                {"orderby": "id", "order": "asc", "_fields": mapping.PRODUCT_FIELDS},
                modified_after=modified,
            )
            page = client.get_page("/products", int(state["pg"]), PER_PAGE, params)
            records, skipped = mapping.safe_map(page.data, mapping.product_records, currency)
            following = _next(state, page.total_pages, {"s": "v", "pg": 1, "i": 0, "vp": 1})
            return self._page(
                records, skipped, following, _progress(state, page.total_pages, 0, 60)
            )
        if stage == "v":
            return self._variations(client, state, currency, modified)
        if stage == "o":
            params = _filters(
                {"orderby": "id", "order": "asc", "_fields": mapping.ORDER_FIELDS},
                after=_when(created_since),
                modified_after=modified,
            )
            page = client.get_page("/orders", int(state["pg"]), PER_PAGE, params)
            records, skipped = mapping.safe_map(page.data, mapping.order_records, currency)
            following = _next(state, page.total_pages, {"s": "r", "pg": 1})
            return self._page(
                records, skipped, following, _progress(state, page.total_pages, 0, 80)
            )
        if stage == "r":
            since = _when(updated_since) or _when(created_since)
            params = _filters(
                {"orderby": "id", "order": "asc", "_fields": mapping.REFUND_FIELDS}, after=since
            )
            page = client.get_page("/refunds", int(state["pg"]), PER_PAGE, params)
            records, skipped = mapping.safe_map(page.data, mapping.refund_records, currency)
            following = _next(state, page.total_pages, None)
            return self._page(
                records, skipped, following, _progress(state, page.total_pages, 80, 100)
            )
        raise UnexpectedResponseError()

    def _variations(
        self, client: WooClient, state: dict[str, Any], currency: str, modified: str | None
    ) -> CommercePage:
        params = _filters(
            {"type": "variable", "orderby": "id", "order": "asc", "_fields": "id"},
            modified_after=modified,
        )
        parents = client.get_page("/products", int(state["pg"]), VARIABLE_PER_PAGE, params)
        ids = [p.get("id") for p in parents.data if isinstance(p, dict)]
        index = int(state["i"])
        if index >= len(ids):  # this page of variable products is done
            if parents.total_pages is not None and int(state["pg"]) < parents.total_pages:
                following = {**state, "pg": int(state["pg"]) + 1, "i": 0, "vp": 1}
                return self._page([], 0, following, _progress(state, parents.total_pages, 60, 100))
            return self._page([], 0, None, 100)
        parent = mapping.external_id(ids[index])
        page = client.get_page(
            f"/products/{parent}/variations",
            int(state["vp"]),
            PER_PAGE,
            {"orderby": "id", "order": "asc", "_fields": mapping.VARIATION_FIELDS},
        )
        records, skipped = mapping.safe_map(
            page.data, lambda v, cur: [mapping.variation_record(v, parent, cur)], currency
        )
        if page.total_pages is not None and int(state["vp"]) < page.total_pages:
            following = {**state, "vp": int(state["vp"]) + 1}
        else:
            following = {**state, "i": index + 1, "vp": 1}
        return self._page(
            records, skipped, following, _progress(state, parents.total_pages, 60, 100)
        )

    def _page(
        self,
        records: list[CommerceRecord],
        skipped: int,
        following: dict[str, Any] | None,
        progress: int,
    ) -> CommercePage:
        if skipped:
            logger.warning("woocommerce_records_skipped", extra={"count": skipped})
        return CommercePage(
            records=tuple(records),
            next_cursor=json.dumps(following, separators=(",", ":")) if following else None,
            progress=progress,
        )

    def webhook_target(self, topic: str) -> WebhookTarget:  # noqa: ARG002
        return WebhookTarget(ChangedObject.NONE)

    def fetch_product(self, secrets: Secrets, external_id: str) -> FetchResult:  # noqa: ARG002
        raise UnsupportedOperationError()  # only used by webhooks, which 2B does not have

    def fetch_order(self, secrets: Secrets, external_id: str) -> FetchResult:  # noqa: ARG002
        raise UnsupportedOperationError()

    # ------------------------------------------------------------------ helpers
    def _store(self, params: Mapping[str, str]) -> StoreAddress:
        raw = params.get("store_url")
        if not raw:
            raise InvalidConnectParamsError()
        return normalize_store_url(raw)

    def _client(self, secrets: Secrets) -> tuple[StoreAddress, WooClient]:
        key, secret = secrets.get("consumer_key"), secrets.get("consumer_secret")
        raw = secrets.get("store_url")
        if not isinstance(key, str) or not isinstance(secret, str) or not isinstance(raw, str):
            raise AuthExpiredError("credentials_incomplete")
        store = normalize_store_url(raw)
        client = WooClient(self._http_factory, store, consumer_key=key, consumer_secret=secret)
        return store, client

    def _supported(self, version: object) -> bool:
        if not isinstance(version, str):
            return False
        match = _VERSION.match(version)
        if match is None:
            return False
        return (int(match.group(1)), int(match.group(2))) >= self._min_version


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UnexpectedResponseError()
    return value


def store_timezone(timezone_string: object, gmt_offset: object) -> str | None:
    """The store's IANA time zone from WordPress settings, or ``None`` if it cannot be known.

    WordPress stores either a named zone (``Australia/Sydney``) or a manual UTC offset. A whole
    hour offset maps to ``Etc/GMT±N`` (POSIX sign: ``UTC+10`` is ``Etc/GMT-10``); a fractional
    offset has no IANA equivalent, so the figures could not be dated correctly: ``None``.
    """
    if isinstance(timezone_string, str) and timezone_string and len(timezone_string) <= 64:
        try:
            ZoneInfo(timezone_string)
        except (ZoneInfoNotFoundError, ValueError):
            pass
        else:
            return timezone_string
    try:
        offset = float(str(gmt_offset))
    except ValueError:
        return None
    if offset != int(offset) or not -12 <= offset <= 14:
        return None
    hours = int(offset)
    if hours == 0:
        return "UTC"
    return f"Etc/GMT{'-' if hours > 0 else '+'}{abs(hours)}"


# ------------------------------------------------------------------ paged-import helpers
def _decode(cursor: str | None) -> dict[str, Any]:
    if not cursor:
        return {}
    try:
        state = json.loads(cursor)
    except ValueError:
        raise UnexpectedResponseError() from None
    if not isinstance(state, dict) or state.get("s") not in ("p", "v", "o", "r"):
        raise UnexpectedResponseError()
    for key in ("pg", "i", "vp"):
        value = state.get(key, 1)
        if not isinstance(value, int) or not 0 <= value <= 1_000_000:
            raise UnexpectedResponseError()
    return state


def _when(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") if moment else None


def _filters(base: dict[str, str | int], **dates: str | None) -> dict[str, str | int]:
    params = dict(base)
    chosen = {k: v for k, v in dates.items() if v}
    if chosen:
        params.update(chosen)
        params["dates_are_gmt"] = "true"
    return params


def _next(
    state: dict[str, Any], total_pages: int | None, after: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The next page of this stage, or the first of the following stage."""
    page = int(state["pg"])
    if total_pages is not None and page < total_pages:
        return {**state, "pg": page + 1}
    return {**after, "c": state["c"]} if after is not None else None


def _progress(state: dict[str, Any], total_pages: int | None, low: int, high: int) -> int:
    if not total_pages:
        return high
    done = min(int(state["pg"]), total_pages) / total_pages
    return int(low + (high - low) * done)
