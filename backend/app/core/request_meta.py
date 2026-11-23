"""Client metadata for security events and throttling."""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request

from app.core.settings import Settings

USER_AGENT_MAX = 200


@dataclass(frozen=True)
class RequestMeta:
    ip: str
    user_agent: str | None


def client_ip(request: Request, settings: Settings) -> str:
    if settings.TRUSTED_PROXY_COUNT > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(hops) >= settings.TRUSTED_PROXY_COUNT:
            return hops[-settings.TRUSTED_PROXY_COUNT]
    return request.client.host if request.client else "unknown"


def request_meta(request: Request, settings: Settings) -> RequestMeta:
    ua = request.headers.get("user-agent")
    return RequestMeta(
        ip=client_ip(request, settings), user_agent=ua[:USER_AGENT_MAX] if ua else None
    )
