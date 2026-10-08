"""/api/v1 router composition."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import health
from app.domains.audit.router import router as audit_router
from app.domains.identity.router import router as identity_router
from app.domains.organizations.router import router as organizations_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(identity_router)
api_router.include_router(organizations_router)
api_router.include_router(audit_router)
