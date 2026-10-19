"""Google sign-in shared by Google Ads (Phase 3) and Google Analytics (Phase 5).

One Google Cloud project and OAuth client serve both products (PHASE_05_PLAN Q-5-2), but each
is its own connection with its own, smallest permission. This module holds what they share:

* Google's OAuth 2.0 web-server flow with **PKCE** (S256) and **offline access** — a 1-hour
  access token and a long-lived refresh token, both encrypted at rest (1B);
* ``openid`` only for Google's stable account id (``sub``), to recognise a reconnect by the
  same person. No email, name or picture is requested or stored;
* the ID token comes straight from Google's token endpoint over TLS, so its claims are read
  without a signature check (OpenID Connect Core §3.1.3.7); issuer, audience and expiry are
  checked;
* **fixed Google hosts only** (the token and revocation endpoints; the browser alone opens the
  consent page); no redirects followed. Response bodies, Google's messages and tokens never
  enter exceptions or logs.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

from app.core.clock import Clock
from app.providers.base.errors import (
    AuthExpiredError,
    InvalidRequestError,
    MissingScopesError,
    RateLimitedError,
    RetryableError,
)
from app.providers.base.types import AuthorizationRequest, ConnectResult
from app.providers.http.client import SafeHttpClient, SafeResponse

HttpFactory = Callable[[], SafeHttpClient]
Secrets = Mapping[str, Any]

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"  # opened by the browser only
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - an endpoint, not a secret
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


class SignInRejectedError(AuthExpiredError):
    """Google refused the sign-in grant (revoked, expired, or a testing-mode limit)."""

    code = "google_sign_in_rejected"


class UnexpectedResponseError(RetryableError):
    code = "unexpected_response"


def _json(response: SafeResponse) -> Any:
    try:
        return json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        raise UnexpectedResponseError() from None


def positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class GoogleSignIn:
    """The token and revocation endpoints of Google's OAuth 2.0 server."""

    def __init__(self, http_factory: HttpFactory) -> None:
        self._http_factory = http_factory

    def token(self, data: dict[str, str]) -> dict[str, Any]:
        """``POST /token`` (code exchange or refresh). A refused grant → ``SignInRejected``."""
        client = self._http_factory()
        try:
            response = client.request(
                "POST",
                TOKEN_URL,
                data=data,
                headers={"Accept": "application/json"},
                follow_redirects=False,
            )
        finally:
            client.close()
        if response.status_code in (400, 401):
            body = _json(response) if response.content else {}
            error = body.get("error") if isinstance(body, dict) else None
            if error in ("invalid_grant", "unauthorized_client", "invalid_client"):
                raise SignInRejectedError()
            raise InvalidRequestError()
        if response.status_code == 429:
            raise RateLimitedError()
        if response.status_code >= 500:
            raise RetryableError("server_error")
        if response.status_code != 200:
            raise InvalidRequestError()
        body = _json(response)
        if not isinstance(body, dict):
            raise UnexpectedResponseError()
        return body

    def revoke(self, token: str) -> None:
        """``POST /revoke``. A token Google no longer knows counts as revoked."""
        client = self._http_factory()
        try:
            response = client.request(
                "POST",
                REVOKE_URL,
                data={"token": token},
                headers={"Accept": "application/json"},
                follow_redirects=False,
            )
        finally:
            client.close()
        if response.status_code == 200 or response.status_code == 400:
            return  # 400 = invalid_token: already revoked or expired
        if response.status_code >= 500 or response.status_code == 429:
            raise RetryableError("server_error")
        raise InvalidRequestError()


class GoogleOAuth:
    """Google sign-in for one product: its scopes, the one it requires, and its label."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        http_factory: HttpFactory,
        clock: Clock,
        product_scope: str,
        label: str,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("Google sign-in needs a client id and a client secret")
        self.client_id = client_id
        self._client_secret = client_secret
        self._clock = clock
        self.product_scope = product_scope
        self.scopes = (product_scope, "openid")
        self.label = label
        self.sign_in = GoogleSignIn(http_factory)

    def authorization_url(self, request: AuthorizationRequest) -> str:
        if not request.code_challenge:
            raise InvalidRequestError()  # PKCE is required
        query = {
            "client_id": self.client_id,
            "redirect_uri": request.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",  # a refresh token, for syncs while the person is away
            "prompt": "consent",  # a reconnect gets a new refresh token (to confirm live)
            "include_granted_scopes": "false",  # each Google product is its own grant
            "state": request.state,
            "code_challenge": request.code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    def complete(
        self, params: Mapping[str, str], *, redirect_uri: str, code_verifier: str | None
    ) -> ConnectResult:
        code = params.get("code", "")
        if not code or len(code) > 1024 or not code_verifier:
            raise InvalidRequestError()
        # Granular consent: a person may untick the product's permission on the consent screen.
        if self.product_scope not in params.get("scope", "").split():
            raise MissingScopesError()
        token = self.sign_in.token(
            {
                "code": code,
                "client_id": self.client_id,
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
        if self.product_scope not in granted:
            raise MissingScopesError()
        return ConnectResult(
            secrets={"access_token": access, "refresh_token": refresh},
            granted_scopes=granted,
            account_label=self.label,
            token_expires_in_seconds=positive_int(token.get("expires_in")),
            refresh_expires_in_seconds=positive_int(token.get("refresh_token_expires_in")),
            external_account_id=self.subject(token.get("id_token")),
            account_per_organization=True,  # the same Google sign-in may serve two
        )

    def subject(self, id_token: Any) -> str:
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
            or claims.get("aud") != self.client_id
            or not isinstance(expires, int | float)
            or expires < self._clock.now().timestamp()
            or not isinstance(subject, str)
            or not subject.isdigit()
            or len(subject) > 64
        ):
            raise InvalidRequestError()
        return subject

    def refresh(self, secrets: Secrets) -> ConnectResult:
        """A new access token from the refresh token. Google usually keeps the same refresh
        token; when it sends a new one, that one is saved."""
        refresh = secrets.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            raise AuthExpiredError("refresh_unavailable")
        try:
            token = self.sign_in.token(
                {
                    "client_id": self.client_id,
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
            account_label=self.label,
            token_expires_in_seconds=positive_int(token.get("expires_in")),
            refresh_expires_in_seconds=positive_int(token.get("refresh_token_expires_in")),
        )

    def revoke(self, secrets: Secrets) -> None:
        """Disconnect: revoking the refresh token at Google also ends its access tokens."""
        token = secrets.get("refresh_token") or secrets.get("access_token")
        if isinstance(token, str) and token:
            self.sign_in.revoke(token)
