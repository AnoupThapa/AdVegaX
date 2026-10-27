"""Standard error envelope and exception handling (API_SPECIFICATION §2)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.correlation import get_correlation_id

logger = logging.getLogger("advegax.errors")


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"
    message = "The request could not be processed."

    def __init__(
        self, message: str | None = None, *, details: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or []


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "Request validation failed."


class Unauthenticated(AppError):
    status_code = 401
    code = "UNAUTHENTICATED"
    message = "Authentication is required."


class InvalidCredentials(AppError):
    status_code = 401
    code = "INVALID_CREDENTIALS"
    message = "Email or password is incorrect."


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"
    message = "You do not have permission to perform this action."


class EmailNotVerified(AppError):
    status_code = 403
    code = "EMAIL_NOT_VERIFIED"
    message = "Verify your email address first."


class CsrfFailed(AppError):
    status_code = 403
    code = "CSRF_FAILED"
    message = "The request could not be verified."


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"
    message = "The requested resource was not found."


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"
    message = "The request conflicts with the current state."


class InvalidToken(AppError):
    status_code = 400
    code = "INVALID_TOKEN"
    message = "The link is invalid or has expired."


class PayloadTooLarge(AppError):
    status_code = 413
    code = "PAYLOAD_TOO_LARGE"
    message = "The request body is too large."


class UnsupportedMediaType(AppError):
    status_code = 415
    code = "UNSUPPORTED_MEDIA_TYPE"
    message = "Requests must use application/json."


class RateLimited(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "Too many requests. Try again later."


class InvalidWebhookSignature(AppError):
    """Platform webhooks: missing/wrong signature or a stale (replayed) delivery. Shopify
    requires 401 here; nothing is stored."""

    status_code = 401
    code = "INVALID_SIGNATURE"
    message = "The request could not be verified."


class InvalidWebhook(AppError):
    status_code = 400
    code = "INVALID_WEBHOOK"
    message = "The webhook could not be processed."


class ServiceUnavailable(AppError):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"
    message = "The service is temporarily unavailable."


class AiLimitReached(AppError):
    """Phase 8: the organization's daily number of AI runs is used up (Q-8-8)."""

    status_code = 429
    code = "AI_LIMIT_REACHED"
    message = "Today's AI planning limit for this organization is reached. Try again tomorrow."


class AiUnavailableError(AppError):
    """Phase 8: the AI provider did not answer (down, overloaded, time limit, not set up)."""

    status_code = 503
    code = "AI_UNAVAILABLE"
    message = "The AI planner is not available right now. Try again later."


class AiAnswerRejected(AppError):
    """Phase 8: the model's answer failed AdVegaX's checks twice; ``details`` say why."""

    status_code = 422
    code = "AI_ANSWER_REJECTED"
    message = "The AI's answer did not pass AdVegaX's checks, so nothing was saved."


class ProductNotPlannable(AppError):
    """Phase 8: this product cannot be planned now (inactive, out of stock, no ad platform,
    a budget below the platforms' minimums); ``details`` say why."""

    status_code = 422
    code = "PRODUCT_NOT_PLANNABLE"
    message = "A strategy cannot be made for this product right now."


class StrategyArchived(AppError):
    """Phase 8: an archived strategy is kept as it was and cannot be changed."""

    status_code = 409
    code = "STRATEGY_ARCHIVED"
    message = "This strategy is archived and can no longer be changed."


class StrategyNotReady(AppError):
    """Phase 9: creatives are drafted only from a strategy marked ready."""

    status_code = 409
    code = "STRATEGY_NOT_READY"
    message = "Mark the strategy ready before making creatives from it."


class CreativeChecksFailed(AppError):
    """Phase 9: approval refused; ``details`` list each check that failed."""

    status_code = 422
    code = "CREATIVE_CHECKS_FAILED"
    message = "This creative does not pass AdVegaX's checks yet."


class CreativeNotEditable(AppError):
    """Phase 9: only the latest version of a creative that is not archived can change."""

    status_code = 409
    code = "CREATIVE_NOT_EDITABLE"
    message = "This version can no longer be changed."


class AssetInvalid(AppError):
    """Phase 9: an upload that is not an acceptable image; ``details`` say why."""

    status_code = 422
    code = "ASSET_INVALID"
    message = "This file is not an image AdVegaX can use."


class ActionsDisabled(AppError):
    """Phase 10A: the installation's or the organization's switch stops every change."""

    status_code = 409
    code = "ACTIONS_DISABLED"
    message = "Changes to ad accounts are switched off."


class ActionInvalid(AppError):
    """Phase 10A: a requested change failed AdVegaX's checks; ``details`` list each one."""

    status_code = 422
    code = "ACTION_INVALID"
    message = "This change does not pass AdVegaX's checks."


class ActionDuplicate(AppError):
    """Phase 10A: the same change is already waiting or running for this campaign."""

    status_code = 409
    code = "ACTION_DUPLICATE"
    message = "This change has already been requested."


class ActionNotAllowed(AppError):
    """Phase 10A: changes are not allowed for this connection (or its permission is missing)."""

    status_code = 409
    code = "ACTION_NOT_ALLOWED"
    message = "Changes are not allowed for this connection."


class ActionStale(AppError):
    """Phase 10A: the campaign changed (or too much time passed) since the request."""

    status_code = 409
    code = "ACTION_STALE"
    message = "The campaign changed since this was requested; request it again."


class SecondPersonRequired(AppError):
    """Phase 10A: the organization requires someone other than the requester to approve."""

    status_code = 409
    code = "SECOND_PERSON_REQUIRED"
    message = "Someone other than the requester must approve this change."


def error_body(
    code: str, message: str, details: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details or []},
        "meta": {"request_id": get_correlation_id()},
    }


def error_response(error: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=error_body(error.code, error.message, error.details),
        headers={"Cache-Control": "no-store"},
    )


_HTTP_CODES = {
    404: ("NOT_FOUND", "The requested resource was not found."),
    405: ("METHOD_NOT_ALLOWED", "The method is not allowed for this resource."),
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "location": [str(p) for p in err.get("loc", ())],
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        return error_response(ValidationFailed(details=details))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_CODES.get(exc.status_code, ("HTTP_ERROR", "The request failed."))
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message),
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content=error_body("INTERNAL_ERROR", "An unexpected error occurred."),
            headers={"Cache-Control": "no-store"},
        )
