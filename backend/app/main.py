"""AdVegaX API application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.correlation import CorrelationIdMiddleware
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.security.csrf import CSRF_HEADER
from app.core.security.middleware import RequestGuardMiddleware, SecurityHeadersMiddleware
from app.core.settings import Settings, get_settings
from app.runtime import Runtime, build_runtime


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.LOG_LEVEL)
    runtime = runtime or build_runtime(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        runtime.close()

    docs = not settings.is_deployed
    app = FastAPI(
        title="AdVegaX API",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json" if docs else None,
        docs_url="/api/v1/docs" if docs else None,
        redoc_url=None,
    )
    app.state.runtime = runtime
    install_error_handlers(app)
    app.include_router(api_router)

    # Added innermost first: RequestGuard → CORS → SecurityHeaders → CorrelationId (outermost).
    app.add_middleware(RequestGuardMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", CSRF_HEADER, "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(CorrelationIdMiddleware)
    return app
