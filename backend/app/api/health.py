"""Liveness and readiness probes."""

from __future__ import annotations

import logging

import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import RuntimeDep
from app.core.errors import ServiceUnavailable, error_response

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger("advegax.health")


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=None)
def ready(rt: RuntimeDep) -> dict[str, str] | JSONResponse:
    try:
        with rt.db.app_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        rt.redis.ping()
    except (SQLAlchemyError, redis.RedisError) as exc:
        logger.warning("readiness_failed", extra={"error_type": type(exc).__name__})
        return error_response(ServiceUnavailable())
    return {"status": "ok"}
