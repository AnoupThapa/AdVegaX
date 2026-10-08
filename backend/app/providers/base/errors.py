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
