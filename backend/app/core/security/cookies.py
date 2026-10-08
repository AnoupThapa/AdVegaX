"""Cookie helpers. All cookies are HttpOnly, SameSite=Lax and host-only."""

from __future__ import annotations

from starlette.responses import Response

from app.core.settings import Settings


def _set(response: Response, settings: Settings, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        path="/",
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    _set(
        response,
        settings,
        settings.SESSION_COOKIE_NAME,
        token,
        int(settings.SESSION_ABSOLUTE_TIMEOUT.total_seconds()),
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def set_csrf_cookie(response: Response, settings: Settings, token: str) -> None:
    _set(
        response,
        settings,
        settings.CSRF_COOKIE_NAME,
        token,
        int(settings.SESSION_ABSOLUTE_TIMEOUT.total_seconds()),
    )
