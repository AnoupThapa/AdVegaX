"""/api/v1 router composition."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import health
from app.domains.advertising.router import router as advertising_router
from app.domains.analytics.router import router as analytics_router
from app.domains.audit.router import router as audit_router
from app.domains.commerce.router import router as commerce_router
from app.domains.creative.router import router as creative_router
from app.domains.funnel.router import router as funnel_router
from app.domains.identity.router import router as identity_router
from app.domains.integrations.router import router as integrations_router
from app.domains.metrics.router import router as metrics_router
from app.domains.organizations.router import router as organizations_router
from app.domains.strategy.router import router as strategy_router
from app.domains.webhooks.router import router as webhooks_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(identity_router)
api_router.include_router(organizations_router)
api_router.include_router(audit_router)
api_router.include_router(integrations_router)
api_router.include_router(commerce_router)
api_router.include_router(advertising_router)
api_router.include_router(analytics_router)
api_router.include_router(metrics_router)
api_router.include_router(funnel_router)
api_router.include_router(strategy_router)
api_router.include_router(creative_router)
api_router.include_router(webhooks_router)
