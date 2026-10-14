"""HTTP security middleware: headers, body-size and content-type guards, CSRF and Origin checks."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.errors import CsrfFailed, PayloadTooLarge, UnsupportedMediaType, error_response
from app.core.security.csrf import CSRF_HEADER, is_valid_csrf, session_binding
from app.core.settings import Settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Server-to-server endpoints authenticated by the platform's own signature over the raw body
# (PHASE_02A_PLAN §7). They skip only the browser checks (Origin + CSRF); the size and
# content-type limits still apply. Keep this list short and explicit.
CSRF_EXEMPT_PATH = re.compile(
    r"/api/v1/webhooks/[a-z0-9_]{1,32}"  # platform webhooks (2A-05)
    r"|/api/v1/connections/[a-z0-9_]{1,32}/credentials"  # platform-posted keys (2B-04)
)
Next = Callable[[Request], Awaitable[Response]]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, settings: Settings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._hsts = settings.is_deployed

    async def dispatch(self, request: Request, call_next: Next) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("Cache-Control", "no-store")
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "no-referrer"
        headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if self._hsts:
            headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


def _origin_of(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


class RequestGuardMiddleware(BaseHTTPMiddleware):
    """Rejects oversized and non-JSON bodies and enforces Origin + CSRF on unsafe methods."""

    def __init__(self, app: object, settings: Settings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._settings = settings
        self._allowed_origins = set(settings.CORS_ALLOWED_ORIGINS)

    async def dispatch(self, request: Request, call_next: Next) -> Response:
        if request.method in SAFE_METHODS:
            return await call_next(request)

        length = request.headers.get("content-length")
        if length is not None and (
            not length.isdigit() or int(length) > self._settings.MAX_REQUEST_BYTES
        ):
            return error_response(PayloadTooLarge())
        body = await request.body()
        if len(body) > self._settings.MAX_REQUEST_BYTES:
            return error_response(PayloadTooLarge())
        if body:
            content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type != "application/json":
                return error_response(UnsupportedMediaType())

        if request.method == "POST" and CSRF_EXEMPT_PATH.fullmatch(request.url.path):
            return await call_next(request)

        origin = _origin_of(request.headers.get("origin")) or _origin_of(
            request.headers.get("referer")
        )
        if origin is None or origin not in self._allowed_origins:
            return error_response(CsrfFailed())

        session_token = request.cookies.get(self._settings.SESSION_COOKIE_NAME)
        if not is_valid_csrf(
            self._settings.SECRET_KEY.get_secret_value(),
            header_token=request.headers.get(CSRF_HEADER),
            cookie_token=request.cookies.get(self._settings.CSRF_COOKIE_NAME),
            binding=session_binding(session_token),
        ):
            return error_response(CsrfFailed())
        return await call_next(request)
