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
from collections.abc import Iterator, Mapping
from datetime import date
from typing import Any
from urllib.parse import urlencode

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
    SyncSummary,
    WebhookDelivery,
)
from app.providers.google_ads.client import (
    AUTHORIZE_URL,
    GoogleAdsClient,
    GoogleSignIn,
    HttpFactory,
    SignInRejectedError,
)

ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
SCOPES = (ADS_SCOPE, "openid")
ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


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
    def discover_resources(self, secrets: Secrets) -> list[ResourceDescriptor]:  # noqa: ARG002
        raise UnsupportedOperationError()  # task 3-04

    def read_account(self, secrets: Secrets, account: AdAccountRef) -> AdAccountState:  # noqa: ARG002
        raise UnsupportedOperationError()  # task 3-05

    def read_structure(
        self,
        secrets: Secrets,  # noqa: ARG002
        account: AdAccountRef,  # noqa: ARG002
    ) -> Iterator[AdStructureRecord]:
        raise UnsupportedOperationError()  # task 3-05

    def read_performance(
        self,
        secrets: Secrets,  # noqa: ARG002
        account: AdAccountRef,  # noqa: ARG002
        level: AdLevel,  # noqa: ARG002
        first_day: date,  # noqa: ARG002
        last_day: date,  # noqa: ARG002
    ) -> Iterator[AdPerformanceRecord]:
        raise UnsupportedOperationError()  # task 3-06


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
