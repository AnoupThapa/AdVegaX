"""Meta Ads provider — sign-in and token lifecycle (Phase 4, task 4-02; PHASE_04_PLAN §6).

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

import logging
from collections.abc import Iterator, Mapping
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
from app.providers.meta_ads.client import (
    LOGIN_DIALOG,
    HttpFactory,
    MetaGraphClient,
    MetaSignInRejectedError,
    UnexpectedResponseError,
)

logger = logging.getLogger("advegax.providers.meta_ads")

ADS_READ = "ads_read"
REQUIRED_SCOPES = frozenset({ADS_READ})
WANTED_SCOPES = frozenset({ADS_READ, "business_management"})


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
    ) -> None:
        if not app_id or not app_secret or not login_config_id:
            raise ValueError("Meta needs an app id, an app secret and a login configuration id")
        self._app_id = app_id
        self._app_secret = app_secret
        self._config_id = login_config_id
        self._clock = clock
        self.graph = MetaGraphClient(http_factory, api_version, app_secret)

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
    def discover_resources(self, secrets: Secrets) -> list[ResourceDescriptor]:  # noqa: ARG002
        return []  # task 4-03

    def read_account(self, secrets: Secrets, account: AdAccountRef) -> AdAccountState:  # noqa: ARG002
        raise UnsupportedOperationError()  # task 4-04

    def read_structure(
        self,
        secrets: Secrets,  # noqa: ARG002
        account: AdAccountRef,  # noqa: ARG002
    ) -> Iterator[AdStructureRecord]:
        raise UnsupportedOperationError()  # task 4-04

    def read_performance(
        self,
        secrets: Secrets,  # noqa: ARG002
        account: AdAccountRef,  # noqa: ARG002
        level: AdLevel,  # noqa: ARG002
        first_day: date,  # noqa: ARG002
        last_day: date,  # noqa: ARG002
    ) -> Iterator[AdPerformanceRecord]:
        raise UnsupportedOperationError()  # task 4-05


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
