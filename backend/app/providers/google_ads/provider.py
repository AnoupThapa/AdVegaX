"""Google Ads provider — sign-in and token lifecycle (Phase 3, task 3-03; PHASE_03_PLAN §6).

Read-only. Google's OAuth 2.0 web-server flow with **PKCE** and **offline access**: a 1-hour
access token and a long-lived refresh token, both encrypted at rest (1B). Scopes:

* ``https://www.googleapis.com/auth/adwords`` — Google Ads (the same scope covers read and
  write, so read-only is enforced in code: only three read calls exist, tests/security);
* ``openid`` — only so the stable Google account id (``sub``) in the ID token can recognise a
  reconnect by the same person. No email, name or picture is requested or stored.

The ID token comes straight from Google's token endpoint over TLS, so its claims are read
without a signature check (OpenID Connect Core §3.1.3.7); issuer, audience and expiry are
checked. Discovery, structure and performance follow in tasks 3-04 … 3-06.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.clock import Clock
from app.providers.base.capabilities import Capability, ProviderCapabilities
from app.providers.base.errors import (
    AuthExpiredError,
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
    ResourceKind,
    SyncSummary,
    WebhookDelivery,
)
from app.providers.google_ads import mapping, queries
from app.providers.google_ads.client import (
    AUTHORIZE_URL,
    AccountNotEnabledError,
    DeveloperTokenNotApprovedError,
    GoogleAdsClient,
    GoogleSignIn,
    HttpFactory,
    NoAccountAccessError,
    NotAdsUserError,
    SignInRejectedError,
    UnexpectedResponseError,
    valid_customer_id,
)
from app.providers.google_ads.queries import ACCOUNT, AD_GROUPS, ADS, BUDGETS, CAMPAIGNS, HIERARCHY

logger = logging.getLogger("advegax.providers.google_ads")

ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
SCOPES = (ADS_SCOPE, "openid")
ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
# Discovery limits: each manager read costs one operation of the shared daily allowance.
MAX_DIRECT_ACCOUNTS = 500
MAX_MANAGERS = 200
MAX_ACCOUNTS = 5000
# Errors that make one account unusable without failing the whole discovery.
_UNUSABLE = (AccountNotEnabledError, NoAccountAccessError, DeveloperTokenNotApprovedError)


def _unusable(customer_id: str, reason: str) -> ResourceDescriptor:
    return ResourceDescriptor(
        kind=ResourceKind.AD_ACCOUNT, external_id=customer_id, unavailable_reason=reason
    )


def _zone(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return value


@dataclass(frozen=True)
class _Client:
    """One ``customer_client`` row (camelCase JSON; int64 values arrive as strings)."""

    id: str
    level: int
    manager: bool
    name: str | None
    currency: str | None
    timezone: str | None
    status: str

    @property
    def label(self) -> str:
        return self.name or self.id

    @classmethod
    def parse(cls, row: dict[str, Any]) -> _Client | None:
        data = row.get("customerClient")
        if not isinstance(data, dict):
            return None
        raw = data.get("id") or str(data.get("clientCustomer", "")).removeprefix("customers/")
        try:
            customer_id = valid_customer_id(str(raw))
            level = int(data.get("level", -1))
        except (InvalidRequestError, TypeError, ValueError):
            return None
        currency = data.get("currencyCode")
        name = data.get("descriptiveName")
        return cls(
            id=customer_id,
            level=level,
            manager=data.get("manager") is True,
            name=name[:255] if isinstance(name, str) and name else None,
            currency=currency if isinstance(currency, str) and len(currency) == 3 else None,
            timezone=_zone(data.get("timeZone")),
            status=str(data.get("status", "")),
        )

    def descriptor(self, *, group_path: str | None, access_hint: str | None) -> ResourceDescriptor:
        reason = None
        if self.status != "ENABLED":
            reason = "account_not_enabled"  # cancelled, suspended or closed
        elif self.currency is None or self.timezone is None:
            reason = "account_details_missing"
        return ResourceDescriptor(
            kind=ResourceKind.AD_ACCOUNT,
            external_id=self.id,
            display_name=self.name,
            currency=self.currency,
            timezone=self.timezone,
            unavailable_reason=reason,
            group_path=group_path[:1024] if group_path else None,
            access_hint=access_hint,
        )


class GoogleAdsProvider:
    code = "google_ads"
    display_name = "Google Ads"
    category = ProviderCategory.ADVERTISING
    auth_scheme = AuthScheme.OAUTH2
    capabilities = ProviderCapabilities(
        frozenset({Capability.PKCE, Capability.TOKEN_REFRESH, Capability.TOKEN_REVOCATION})
    )
    test_only = False
    rate_limit = (5.0, 10)  # per connection; the shared daily allowance is paced in 3-07

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        developer_token: str,
        api_version: str,
        http_factory: HttpFactory,
        clock: Clock,
    ) -> None:
        if not client_id or not client_secret or not developer_token:
            raise ValueError("Google Ads needs a client id, client secret and developer token")
        self._client_id = client_id
        self._client_secret = client_secret
        self._clock = clock
        self._sign_in = GoogleSignIn(http_factory)
        self.ads = GoogleAdsClient(http_factory, api_version, developer_token)

    # ------------------------------------------------------------------ connect
    def prepare_connect(self, params: Mapping[str, str]) -> PreparedConnect:
        if params:  # nothing to type: the person chooses their Google account at Google
            raise InvalidConnectParamsError()
        return PreparedConnect()

    def authorization_url(self, request: AuthorizationRequest) -> str:
        if not request.code_challenge:
            raise InvalidRequestError()  # PKCE is required for this provider
        query = {
            "client_id": self._client_id,
            "redirect_uri": request.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",  # a refresh token, for syncs while the person is away
            "prompt": "consent",  # a reconnect gets a new refresh token (to confirm live)
            "include_granted_scopes": "false",  # GA4 (Phase 5) is a separate grant
            "state": request.state,
            "code_challenge": request.code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    def complete_authorization(
        self,
        params: Mapping[str, str],
        *,
        redirect_uri: str,
        code_verifier: str | None,
        provider_params: Mapping[str, str],  # noqa: ARG002 - nothing is typed for Google
    ) -> ConnectResult:
        code = params.get("code", "")
        if not code or len(code) > 1024 or not code_verifier:
            raise InvalidRequestError()
        # Granular consent: a person may untick Google Ads on the consent screen.
        if ADS_SCOPE not in params.get("scope", "").split():
            raise MissingScopesError()
        token = self._sign_in.token(
            {
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            }
        )
        access, refresh = token.get("access_token"), token.get("refresh_token")
        if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
            raise InvalidRequestError()
        granted = tuple(sorted(str(token.get("scope", "")).split()))
        if ADS_SCOPE not in granted:
            raise MissingScopesError()
        subject = self._subject(token.get("id_token"))
        return ConnectResult(
            secrets={"access_token": access, "refresh_token": refresh},
            granted_scopes=granted,
            account_label="Google Ads",
            token_expires_in_seconds=_positive_int(token.get("expires_in")),
            refresh_expires_in_seconds=_positive_int(token.get("refresh_token_expires_in")),
            external_account_id=subject,
            account_per_organization=True,  # the same Google sign-in may serve two (Q-3-11)
        )

    def _subject(self, id_token: Any) -> str:
        """The stable Google account id from the ID token (claims only; see module doc)."""
        if not isinstance(id_token, str) or id_token.count(".") != 2 or len(id_token) > 8192:
            raise InvalidRequestError()
        payload = id_token.split(".")[1]
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except (ValueError, UnicodeDecodeError):
            raise InvalidRequestError() from None
        if not isinstance(claims, dict):
            raise InvalidRequestError()
        subject, expires = claims.get("sub"), claims.get("exp")
        if (
            claims.get("iss") not in ISSUERS
            or claims.get("aud") != self._client_id
            or not isinstance(expires, int | float)
            or expires < self._clock.now().timestamp()
            or not isinstance(subject, str)
            or not subject.isdigit()
            or len(subject) > 64
        ):
            raise InvalidRequestError()
        return subject

    def verify_install(self, params: Mapping[str, str]) -> str:  # noqa: ARG002
        raise UnsupportedOperationError()

    # ------------------------------------------------------------------ token lifecycle
    def refresh_credentials(self, secrets: Secrets) -> ConnectResult:
        """A new access token from the refresh token. Google usually keeps the same refresh
        token; when it sends a new one, that one is saved."""
        refresh = secrets.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            raise AuthExpiredError("refresh_unavailable")
        try:
            token = self._sign_in.token(
                {
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                }
            )
        except InvalidRequestError:
            raise SignInRejectedError() from None
        access = token.get("access_token")
        if not isinstance(access, str) or not access:
            raise SignInRejectedError()
        new_refresh = token.get("refresh_token")
        kept = new_refresh if isinstance(new_refresh, str) and new_refresh else refresh
        return ConnectResult(
            secrets={"access_token": access, "refresh_token": kept},
            granted_scopes=tuple(sorted(str(token.get("scope", "")).split())),
            account_label="Google Ads",
            token_expires_in_seconds=_positive_int(token.get("expires_in")),
            refresh_expires_in_seconds=_positive_int(token.get("refresh_token_expires_in")),
        )

    def revoke(self, secrets: Secrets) -> None:
        """Disconnect: revoking the refresh token at Google also ends its access tokens."""
        token = secrets.get("refresh_token") or secrets.get("access_token")
        if isinstance(token, str) and token:
            self._sign_in.revoke(token)

    # ------------------------------------------------------------------ not used by Google Ads
    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookDelivery:  # noqa: ARG002
        raise UnsupportedOperationError()

    def sync_resource(self, secrets: Secrets, resource: ResourceDescriptor) -> SyncSummary:  # noqa: ARG002
        raise UnsupportedOperationError()  # ad accounts are imported by the core (3-05, 3-06)

    # ------------------------------------------------------------------ reads (3-04 … 3-06)
    def discover_resources(self, secrets: Secrets) -> list[ResourceDescriptor]:
        """Every advertiser account the signed-in person can reach (task 3-04, Q-3-3).

        Google lists only accounts with **direct** access; accounts under a manager are found
        by reading each manager's hierarchy with the top manager as ``login-customer-id``
        (Google's account-hierarchy sample). Managers are not returned: they have no figures
        of their own and appear as the ``group_path`` of the accounts below them. Accounts
        that cannot be used are returned with a plain ``unavailable_reason``.
        """
        token = str(secrets.get("access_token", ""))
        try:
            direct = self.ads.list_accessible_customers(token)
        except NotAdsUserError:
            return []  # signed in with a Google account that has no Google Ads
        found: dict[str, ResourceDescriptor] = {}
        direct_ids = set(direct)
        managers_read = 0
        for root in direct[:MAX_DIRECT_ACCOUNTS]:
            try:
                rows = self._hierarchy(token, root, root)
            except _UNUSABLE as exc:
                found[root] = _unusable(root, exc.code)
                continue
            managers_read += 1
            me = next((r for r in rows if r.level == 0), None)
            if me is None or not me.manager:
                if me is not None:
                    found[root] = me.descriptor(group_path=None, access_hint=None)
                continue
            # Walk the manager's hierarchy breadth first (each manager read once).
            queue: list[tuple[str, list[str], list[_Client]]] = [(root, [me.label], rows)]
            seen_managers = {root}
            while queue:
                manager, path, children = queue.pop(0)
                for child in children:
                    if child.level != 1 or child.id == manager:
                        continue
                    if child.manager:
                        if child.id in seen_managers or managers_read >= MAX_MANAGERS:
                            continue
                        seen_managers.add(child.id)
                        try:
                            below = self._hierarchy(token, child.id, root)
                        except _UNUSABLE:
                            continue  # a manager we cannot read: its accounts stay hidden
                        managers_read += 1
                        queue.append((child.id, [*path, child.label], below))
                    elif child.id not in direct_ids and child.id not in found:
                        found[child.id] = child.descriptor(
                            group_path=" > ".join(path), access_hint=root
                        )
                    if len(found) >= MAX_ACCOUNTS:
                        return list(found.values())
        return list(found.values())

    def _hierarchy(self, token: str, customer_id: str, login: str) -> list[_Client]:
        rows = self.ads.search_stream(token, customer_id, HIERARCHY, login_customer_id=login)
        return [c for c in (_Client.parse(r) for r in rows) if c is not None]

    def _rows(
        self, secrets: Secrets, account: AdAccountRef, query: str
    ) -> Iterator[dict[str, Any]]:
        return self.ads.search_stream(
            str(secrets.get("access_token", "")),
            account.external_id,
            query,
            login_customer_id=account.access_hint,
        )

    def read_account(self, secrets: Secrets, account: AdAccountRef) -> AdAccountState:
        """The account's name, currency, time zone and status (one operation)."""
        for row in self._rows(secrets, account, ACCOUNT):
            data = row.get("customer")
            if not isinstance(data, dict):
                continue
            currency = data.get("currencyCode")
            timezone = _zone(data.get("timeZone"))
            if not isinstance(currency, str) or len(currency) != 3 or timezone is None:
                raise UnexpectedResponseError()
            name = data.get("descriptiveName")
            return AdAccountState(
                external_id=account.external_id,
                name=name[:255] if isinstance(name, str) and name else None,
                currency=currency,
                timezone=timezone,
                platform_status=mapping.ACCOUNT_STATUSES.get(str(data.get("status")), "closed"),
            )
        raise UnexpectedResponseError()

    def read_structure(
        self, secrets: Secrets, account: AdAccountRef
    ) -> Iterator[AdStructureRecord]:
        """Budgets, campaigns, ad groups and ads — parents first, removed ones included
        (four operations). Rows that cannot be read are skipped and logged by count."""
        skipped = 0
        for query, parse in (
            (BUDGETS, mapping.budget),
            (CAMPAIGNS, mapping.campaign),
            (AD_GROUPS, mapping.ad_group),
            (ADS, mapping.ad),
        ):
            for row in self._rows(secrets, account, query):
                record = parse(row)
                if record is None:
                    skipped += 1
                    continue
                yield record
        if skipped:
            logger.warning("google_ads_rows_skipped", extra={"count": skipped})

    def read_performance(
        self,
        secrets: Secrets,
        account: AdAccountRef,
        level: AdLevel,
        first_day: date,
        last_day: date,
    ) -> Iterator[AdPerformanceRecord]:
        """Daily figures for one level (one operation). Unreadable rows are skipped and
        counted; days without activity are absent (the caller writes real zeros)."""
        if last_day < first_day:
            raise InvalidRequestError()
        query = queries.performance(level.value, first_day.isoformat(), last_day.isoformat())
        skipped = 0
        for row in self._rows(secrets, account, query):
            record = mapping.performance(row, level)
            if record is None or not first_day <= record.day <= last_day:
                skipped += 1
                continue
            yield record
        if skipped:
            logger.warning("google_ads_rows_skipped", extra={"count": skipped})


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
