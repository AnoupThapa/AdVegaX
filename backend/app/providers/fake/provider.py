"""Fake platform for tests and local development only (A16). Never registered when deployed.

Behaves like an OAuth 2.0 platform with PKCE and can be told to fail in specific ways so that
connection, discovery, linking, sync, retry and dead-letter paths are exercised without network.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlencode

from app.providers.base.capabilities import Capability, ProviderCapabilities
from app.providers.base.errors import (
    AuthExpiredError,
    InvalidRequestError,
    PermissionDeniedError,
    RateLimitedError,
    RetryableError,
)
from app.providers.base.interfaces import Secrets
from app.providers.base.pkce import pkce_challenge
from app.providers.base.types import (
    AuthorizationRequest,
    AuthScheme,
    ConnectResult,
    ProviderCategory,
    ResourceDescriptor,
    ResourceKind,
    SyncSummary,
)

AUTHORIZE_URL = "https://fake-platform.invalid/oauth/authorize"
APPROVAL_PREFIX = "approved."


def _default_resources() -> list[ResourceDescriptor]:
    return [
        ResourceDescriptor(
            ResourceKind.AD_ACCOUNT, "fake-acct-101", "Fake Account 101", "AUD", "Australia/Sydney"
        ),
        ResourceDescriptor(
            ResourceKind.AD_ACCOUNT, "fake-acct-102", "Fake Account 102", "USD", "America/New_York"
        ),
        ResourceDescriptor(
            ResourceKind.STORE, "fake-store-1", "Fake Store", "NPR", "Asia/Kathmandu"
        ),
    ]


@dataclass
class FakeBehaviour:
    """Test controls. Counters decrement as failures are produced."""

    resources: list[ResourceDescriptor] = field(default_factory=_default_resources)
    auth_expired: bool = False
    permission_denied: bool = False
    rate_limited_times: int = 0
    retryable_failures: int = 0
    revoke_fails: bool = False
    calls: list[str] = field(default_factory=list)


_lock = threading.Lock()
behaviour = FakeBehaviour()


def reset() -> None:
    global behaviour
    with _lock:
        behaviour = FakeBehaviour()


class FakeProvider:
    code = "fake"
    category = ProviderCategory.ADVERTISING
    auth_scheme = AuthScheme.OAUTH2
    capabilities = ProviderCapabilities(frozenset({Capability.PKCE, Capability.TOKEN_REVOCATION}))
    test_only = True
    rate_limit = (50.0, 50)

    def authorization_url(self, request: AuthorizationRequest) -> str:
        query = {
            "state": request.state,
            "redirect_uri": request.redirect_uri,
            "response_type": "code",
        }
        if request.code_challenge:
            query.update(code_challenge=request.code_challenge, code_challenge_method="S256")
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    def complete_authorization(
        self,
        params: Mapping[str, str],
        *,
        redirect_uri: str,  # noqa: ARG002 - part of the provider contract
        code_verifier: str | None,
    ) -> ConnectResult:
        code = params.get("code", "")
        if not code.startswith(APPROVAL_PREFIX) or code_verifier is None:
            raise InvalidRequestError("invalid_grant")
        if code.removeprefix(APPROVAL_PREFIX) != pkce_challenge(code_verifier):
            raise InvalidRequestError("pkce_mismatch")
        behaviour.calls.append("complete_authorization")
        return ConnectResult(
            secrets={
                "access_token": f"fake-at-{secrets.token_urlsafe(24)}",
                "refresh_token": f"fake-rt-{secrets.token_urlsafe(24)}",
            },
            granted_scopes=("read",),
            account_label="Fake Business",
            token_expires_in_seconds=3600,
        )

    def _check(self, secrets_: Secrets, operation: str) -> None:
        if not str(secrets_.get("access_token", "")).startswith("fake-at-"):
            raise AuthExpiredError()
        with _lock:
            behaviour.calls.append(operation)
            if behaviour.auth_expired:
                raise AuthExpiredError()
            if behaviour.permission_denied:
                raise PermissionDeniedError()
            if behaviour.rate_limited_times > 0:
                behaviour.rate_limited_times -= 1
                raise RateLimitedError(retry_after_seconds=1)
            if behaviour.retryable_failures > 0:
                behaviour.retryable_failures -= 1
                raise RetryableError("temporary_failure")

    def discover_resources(self, secrets: Secrets) -> list[ResourceDescriptor]:
        self._check(secrets, "discover")
        return list(behaviour.resources)

    def sync_resource(self, secrets: Secrets, resource: ResourceDescriptor) -> SyncSummary:
        self._check(secrets, f"sync:{resource.external_id}")
        return SyncSummary(items_synchronized=3, detail={"resource": resource.external_id})

    def revoke(self, secrets: Secrets) -> None:  # noqa: ARG002 - provider contract
        behaviour.calls.append("revoke")
        if behaviour.revoke_fails:
            raise RetryableError("revoke_failed")
