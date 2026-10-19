"""Meta Ads provider (Phase 4; PHASE_04_PLAN §6): sign-in and token lifecycle (4-02), ad
account discovery (4-03), structure (4-04) and daily figures (4-05).

Read-only. **Facebook Login for Business** with a configuration (``config_id``) that asks for
``ads_read`` and ``business_management`` (Q-4-2):

1. the browser opens Meta's login dialog with the configuration id, a single-use ``state``
   and a PKCE challenge (S256; Meta documents PKCE for manually built flows — to confirm with
   Login for Business in Step 0);
2. the callback's code is exchanged **on the server** with the app secret and the PKCE
   verifier for a user access token, which is then exchanged for the **long-lived** token
   (about 60 days);
3. ``/me`` and ``/me/permissions``, signed with ``appsecret_proof`` (so Meta itself confirms
   the token belongs to AdVegaX's app), give the person's Meta user id — kept only to
   recognise a reconnect by the same person; no name, email or picture is requested or
   stored — and the permissions granted, which must include ``ads_read``. Meta's
   ``debug_token`` is not used: it carries the token in the address.

Long-lived user tokens cannot be renewed without the person, so the provider declares no
token refresh: when the token ends, the connection shows "Needs reconnecting" (expiry warnings
come in 4-06). The 90-day data-access expiry does not apply to the ads permissions.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import date
from typing import Any
from urllib.parse import urlencode

from app.core.clock import Clock
from app.providers.base.capabilities import Capability, ProviderCapabilities
from app.providers.base.errors import (
    InvalidConnectParamsError,
    InvalidRequestError,
    MissingScopesError,
    UnsupportedOperationError,
)
from app.providers.base.interfaces import Secrets
from app.providers.base.types import (
    AdAccountRef,
    AdAccountState,
    AdLevel,
    AdPerformanceRecord,
    AdStructureRecord,
    AuthorizationRequest,
    AuthScheme,
    ConnectResult,
    PreparedConnect,
    ProviderCategory,
    ResourceDescriptor,
    SyncSummary,
    WebhookDelivery,
)
from app.providers.meta_ads import mapping
from app.providers.meta_ads.client import (
    LOGIN_DIALOG,
    HttpFactory,
    MetaGraphClient,
    MetaSignInRejectedError,
    ReportFailedError,
    ReportPendingError,
    TooMuchDataError,
    UnexpectedResponseError,
    valid_node,
)

logger = logging.getLogger("advegax.providers.meta_ads")

ADS_READ = "ads_read"
REQUIRED_SCOPES = frozenset({ADS_READ})
WANTED_SCOPES = frozenset({ADS_READ, "business_management"})
ACCOUNT_FIELDS = "id,name,currency,timezone_name,account_status,business{id,name}"
MAX_ACCOUNTS = 5000
CAMPAIGN_FIELDS = (
    "id,name,status,effective_status,objective,buying_type,bid_strategy,"
    "start_time,stop_time,daily_budget,lifetime_budget"
)
AD_SET_FIELDS = (
    "id,name,status,effective_status,campaign_id,optimization_goal,bid_strategy,"
    "daily_budget,lifetime_budget"
)
AD_FIELDS = "id,name,status,effective_status,adset_id,creative{id,name}"
PAGE_SIZE = "500"
INSIGHT_FIELDS = (
    "date_start,date_stop,campaign_id,adset_id,ad_id,impressions,inline_link_clicks,spend,"
    "actions,action_values"
)
META_LEVELS = {
    AdLevel.ACCOUNT: "account",
    AdLevel.CAMPAIGN: "campaign",
    AdLevel.AD_GROUP: "adset",
    AdLevel.AD: "ad",
}
# Asynchronous reports (used only when Meta says a request is too large): checked every few
# seconds within the same job step; a report not done in time is started again later.
REPORT_POLL_SECONDS = 5.0
REPORT_MAX_POLLS = 60


class MetaAdsProvider:
    code = "meta_ads"
    display_name = "Meta"
    category = ProviderCategory.ADVERTISING
    auth_scheme = AuthScheme.OAUTH2
    capabilities = ProviderCapabilities(frozenset({Capability.PKCE, Capability.TOKEN_REVOCATION}))
    test_only = False
    rate_limit = (5.0, 10)  # per connection; Meta's own usage headers pace the rest (4-06)

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        login_config_id: str,
        api_version: str,
        http_factory: HttpFactory,
        clock: Clock,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not app_id or not app_secret or not login_config_id:
            raise ValueError("Meta needs an app id, an app secret and a login configuration id")
        self._app_id = app_id
        self._app_secret = app_secret
        self._config_id = login_config_id
        self._clock = clock
        self._sleep = sleep
        self.graph = MetaGraphClient(
            http_factory,
            api_version,
            app_secret,
            now=lambda: clock.now().timestamp(),
            sleep=sleep,
        )
        # Ad account → currency from the latest ``read_account`` (the importer reads the
        # account just before its structure), so budgets need no second account call. Not
        # secret; an account's currency is the same for every organization.
        self._currencies: dict[str, str] = {}

    # ------------------------------------------------------------------ connect
    def prepare_connect(self, params: Mapping[str, str]) -> PreparedConnect:
        if params:  # nothing to type: the person chooses their account on Meta's page
            raise InvalidConnectParamsError()
        return PreparedConnect()

    def authorization_url(self, request: AuthorizationRequest) -> str:
        if not request.code_challenge:
            raise InvalidRequestError()  # PKCE is required for this provider
        query = {
            "client_id": self._app_id,
            "redirect_uri": request.redirect_uri,
            "response_type": "code",
            "config_id": self._config_id,  # Login for Business: replaces the scope list
            "state": request.state,
            "code_challenge": request.code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{LOGIN_DIALOG.format(version=self.graph.version)}?{urlencode(query)}"

    def complete_authorization(
        self,
        params: Mapping[str, str],
        *,
        redirect_uri: str,
        code_verifier: str | None,
        provider_params: Mapping[str, str],  # noqa: ARG002 - nothing is typed for Meta
    ) -> ConnectResult:
        code = params.get("code", "")
        if not code or len(code) > 2048 or not code_verifier:
            raise InvalidRequestError()
        short = self.graph.exchange(
            {
                "client_id": self._app_id,
                "client_secret": self._app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            }
        )
        short_token = short.get("access_token")
        if not isinstance(short_token, str) or not short_token:
            raise InvalidRequestError()
        long = self.graph.exchange(
            {
                "grant_type": "fb_exchange_token",
                "client_id": self._app_id,
                "client_secret": self._app_secret,
                "fb_exchange_token": short_token,
            }
        )
        token = long.get("access_token")
        if not isinstance(token, str) or not token:
            raise InvalidRequestError()
        info = self.inspect(token)
        granted = info["scopes"]
        if not set(granted) >= REQUIRED_SCOPES:
            raise MissingScopesError()
        return ConnectResult(
            secrets={"access_token": token},
            granted_scopes=tuple(sorted(set(granted) & WANTED_SCOPES)),
            account_label="Meta",
            token_expires_in_seconds=_positive_int(long.get("expires_in")),
            external_account_id=info["user_id"],
            account_per_organization=True,  # the same sign-in may serve two (Q-4-11)
        )

    def inspect(self, token: str) -> dict[str, Any]:
        """Whose token it is and which permissions the person granted (token in the header)."""
        me = self.graph.get(token, "/me", {"fields": "id"})
        user_id = me.get("id")
        if not isinstance(user_id, str) or not user_id.isdigit() or len(user_id) > 32:
            raise MetaSignInRejectedError()
        granted = []
        for row in self.graph.get_all(token, "/me/permissions"):
            name, state = row.get("permission"), row.get("status")
            if not isinstance(name, str) or not isinstance(state, str):
                raise UnexpectedResponseError()
            if state == "granted":
                granted.append(name)
        return {"user_id": user_id, "scopes": granted}

    def verify_install(self, params: Mapping[str, str]) -> str:  # noqa: ARG002
        raise UnsupportedOperationError()

    # ------------------------------------------------------------------ token lifecycle
    def refresh_credentials(self, secrets: Secrets) -> ConnectResult:  # noqa: ARG002
        """Long-lived user tokens cannot be renewed without the person (they sign in again)."""
        raise UnsupportedOperationError()

    def revoke(self, secrets: Secrets) -> None:
        """Disconnect: remove AdVegaX's permission at Meta for the person who connected."""
        token = secrets.get("access_token")
        if isinstance(token, str) and token:
            self.graph.remove_permissions(token)

    # ------------------------------------------------------------------ not used by Meta
    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookDelivery:  # noqa: ARG002
        raise UnsupportedOperationError()

    def sync_resource(self, secrets: Secrets, resource: ResourceDescriptor) -> SyncSummary:  # noqa: ARG002
        raise UnsupportedOperationError()  # ad accounts are imported by the core

    # ------------------------------------------------------------------ reads (4-03 … 4-05)
    def discover_resources(self, secrets: Secrets) -> list[ResourceDescriptor]:
        """Every ad account the person can reach (``me/adaccounts``, which includes accounts
        reached through the businesses they belong to — to confirm live, Step 0 item 2),
        grouped by the business that owns it. Accounts that cannot be used carry a plain
        reason (Q-4-3). Rows AdVegaX cannot read are skipped and counted."""
        token = _token(secrets)
        found: dict[str, ResourceDescriptor] = {}
        skipped = 0
        for row in self.graph.get_all(
            token, "/me/adaccounts", {"fields": ACCOUNT_FIELDS, "limit": "200"}
        ):
            descriptor = mapping.ad_account(row)
            if descriptor is None:
                skipped += 1
                continue
            found.setdefault(descriptor.external_id, descriptor)
            if len(found) >= MAX_ACCOUNTS:
                logger.warning("meta_ads_account_limit_reached", extra={"count": len(found)})
                break
        if skipped:
            logger.warning("meta_ads_rows_skipped", extra={"count": skipped})
        return list(found.values())

    def read_account(self, secrets: Secrets, account: AdAccountRef) -> AdAccountState:
        """The account's name, currency, time zone and status (one call)."""
        node = valid_node(account.external_id)
        row = self.graph.get(_token(secrets), f"/{node}", {"fields": ACCOUNT_FIELDS})
        money, tz = mapping.currency(row.get("currency")), mapping.zone(row.get("timezone_name"))
        if mapping.account_id(row.get("id")) != node or money is None or tz is None:
            raise UnexpectedResponseError()
        platform_status, reason = mapping.account_status(row.get("account_status"))
        self._currencies[node] = money
        return AdAccountState(
            external_id=node,
            name=mapping.text(row.get("name")),
            currency=money,
            timezone=tz,
            platform_status=platform_status,
            unavailable_reason=reason,
        )

    def read_structure(
        self, secrets: Secrets, account: AdAccountRef
    ) -> Iterator[AdStructureRecord]:
        """Campaigns, ad sets and ads — parents first, archived and deleted ones included
        (Meta hides them unless ``effective_status`` is filtered explicitly). Budgets come
        from the object holding them, converted with the account currency's offset (one
        account read, unless the account was just read). Rows that cannot be read are
        skipped and logged by count."""
        token = _token(secrets)
        node = valid_node(account.external_id)
        currency_code = self._currencies.get(node) or self.read_account(secrets, account).currency
        skipped = 0

        def rows(edge: str, fields: str) -> Iterator[dict[str, Any]]:
            return self.graph.get_all(
                token,
                f"/{node}/{edge}",
                {"fields": fields, "limit": PAGE_SIZE, "filtering": _ALL_STATUSES},
            )

        for row in rows("campaigns", CAMPAIGN_FIELDS):
            money = mapping.budget(row, "campaign", currency_code)
            record = mapping.campaign(row, money.external_id if money else None)
            if record is None:
                skipped += 1
                continue
            if money is not None:
                yield money
            yield record
        for row in rows("adsets", AD_SET_FIELDS):
            money = mapping.budget(row, "ad_group", currency_code)
            group = mapping.ad_set(row, money.external_id if money else None)
            if group is None:
                skipped += 1
                continue
            if money is not None:
                yield money
            yield group
        for row in rows("ads", AD_FIELDS):
            item = mapping.ad(row)
            if item is None:
                skipped += 1
                continue
            yield item
        if skipped:
            logger.warning("meta_ads_rows_skipped", extra={"count": skipped})

    def read_performance(
        self,
        secrets: Secrets,
        account: AdAccountRef,
        level: AdLevel,
        first_day: date,
        last_day: date,
    ) -> Iterator[AdPerformanceRecord]:
        """Daily figures for one level, one row per entity and day in the account's time
        zone, with each ad set's own attribution setting (Q-4-6). Archived and deleted
        objects are asked for explicitly, so their days stay readable. When Meta says the
        request is too large, the same request runs as an asynchronous report. Unreadable
        rows are skipped and counted; days without activity are absent (the caller writes
        real zeros at the account level)."""
        if last_day < first_day:
            raise InvalidRequestError()
        token = _token(secrets)
        node = valid_node(account.external_id)
        params = _insights_params(level, first_day, last_day)
        try:
            rows = list(self.graph.get_all(token, f"/{node}/insights", params))
        except TooMuchDataError:
            rows = self._report(token, node, params)
        skipped = 0
        for row in rows:
            record = mapping.performance(row, level)
            if record is None or not first_day <= record.day <= last_day:
                skipped += 1
                continue
            yield record
        if skipped:
            logger.warning("meta_ads_rows_skipped", extra={"count": skipped})

    def _report(self, token: str, node: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """Start, check and read one asynchronous report. Its id is used only here."""
        form = {k: v for k, v in params.items() if k != "limit"}
        report = self.graph.start_report(token, node, form)
        for _ in range(REPORT_MAX_POLLS):
            self._sleep(REPORT_POLL_SECONDS)
            state = self.graph.get(
                token, f"/{report}", {"fields": "async_status,async_percent_completion"}
            )
            status = state.get("async_status")
            if status == "Job Completed":
                return list(self.graph.get_all(token, f"/{report}/insights", {"limit": PAGE_SIZE}))
            if status in ("Job Failed", "Job Skipped"):
                raise ReportFailedError()
            if not isinstance(status, str):
                raise UnexpectedResponseError()
        raise ReportPendingError()  # started again by the job's next attempt


_ALL_STATUSES = json.dumps(
    [{"field": "effective_status", "operator": "IN", "value": list(mapping.EFFECTIVE_STATUSES)}],
    separators=(",", ":"),
)


def _insights_params(level: AdLevel, first_day: date, last_day: date) -> dict[str, str]:
    meta_level = META_LEVELS[level]
    params = {
        "level": meta_level,
        "fields": INSIGHT_FIELDS,
        "time_range": json.dumps(
            {"since": first_day.isoformat(), "until": last_day.isoformat()},
            separators=(",", ":"),
        ),
        "time_increment": "1",
        "use_unified_attribution_setting": "true",
        "limit": PAGE_SIZE,
    }
    if level is not AdLevel.ACCOUNT:
        params["filtering"] = json.dumps(
            [
                {
                    "field": f"{meta_level}.effective_status",
                    "operator": "IN",
                    "value": list(mapping.EFFECTIVE_STATUSES),
                }
            ],
            separators=(",", ":"),
        )
    return params


def _token(secrets: Secrets) -> str:
    token = secrets.get("access_token")
    if not isinstance(token, str) or not token:
        raise MetaSignInRejectedError()
    return token


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
