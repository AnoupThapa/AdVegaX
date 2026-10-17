"""Provider error taxonomy. Messages are codes, never raw provider payloads or secrets."""

from __future__ import annotations


class ProviderError(Exception):
    code = "provider_error"
    retryable = False

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.code)


class RetryableError(ProviderError):
    code = "retryable"
    retryable = True


class RateLimitedError(RetryableError):
    code = "rate_limited"

    def __init__(self, retry_after_seconds: float | None = None) -> None:
        super().__init__(self.code)
        self.retry_after_seconds = retry_after_seconds


class AuthExpiredError(ProviderError):
    code = "auth_expired"


class PermissionDeniedError(ProviderError):
    code = "permission_denied"


class ResourceNotFoundError(ProviderError):
    code = "not_found"


class ResourceUnavailableError(ProviderError):
    """One platform account cannot be used (e.g. a cancelled ad account), while the
    connection itself is fine — never marks the connection's health (Phase 3)."""

    code = "resource_unavailable"


class InvalidRequestError(ProviderError):
    code = "invalid_request"


class UnknownOutcomeError(ProviderError):
    """The request may or may not have taken effect; must be reconciled, never blindly retried."""

    code = "unknown_outcome"


class BlockedDestinationError(ProviderError):
    """The SSRF policy refused the destination (A11)."""

    code = "blocked_destination"


class ResponseTooLargeError(ProviderError):
    code = "response_too_large"


class OutboundTimeoutError(RetryableError):
    code = "timeout"


class InvalidConnectParamsError(InvalidRequestError):
    """Connect parameters from the web app are missing or invalid (e.g. a bad store address)."""

    code = "invalid_connect_params"


class InvalidSignatureError(InvalidRequestError):
    """A platform request (callback, install, webhook) failed signature verification."""

    code = "invalid_signature"


class AccountMismatchError(InvalidRequestError):
    """The platform answered for a different account than the one the flow started with."""

    code = "account_mismatch"


class MissingScopesError(InvalidRequestError):
    """The person approved fewer permissions than AdVegaX needs."""

    code = "missing_scopes"


class UnsupportedOperationError(ProviderError):
    """The provider does not support this operation (declared through its capabilities)."""

    code = "unsupported"
