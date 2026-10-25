"""Import every model so Alembic and tests see the full metadata."""

from app.db.base import Base
from app.domains.advertising.models import (
    Ad,
    AdAccount,
    AdBudget,
    AdCampaign,
    AdGroup,
    AdPerformanceDaily,
    AdSyncState,
)
from app.domains.ai.models import AiModel, AiRun, CampaignStrategy, PromptVersion
from app.domains.analytics.models import AnalyticsDaily, AnalyticsProperty, AnalyticsSyncState
from app.domains.audit.models import AuditLog, SecurityEvent
from app.domains.commerce.models import (
    CommerceSyncState,
    Order,
    OrderItem,
    Product,
    ProductCostHistory,
    ProductVariant,
    Refund,
    RefundItem,
    SalesEntry,
    Store,
)
from app.domains.finance.models import FinancialDaily
from app.domains.fx.models import FxRate
from app.domains.identity.models import User, UserActionToken, UserPasswordCredential, UserSession
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalConnectionCredential,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.jobs.models import JobRun
from app.domains.notifications.models import EmailOutbox
from app.domains.organizations.models import Invitation, Membership, Organization
from app.domains.webhooks.models import WebhookEvent

__all__ = [
    "Ad",
    "AdAccount",
    "AdBudget",
    "AdCampaign",
    "AdGroup",
    "AdPerformanceDaily",
    "AdSyncState",
    "AiModel",
    "AiRun",
    "AnalyticsDaily",
    "AnalyticsProperty",
    "AnalyticsSyncState",
    "AuditLog",
    "Base",
    "CampaignStrategy",
    "CommerceSyncState",
    "EmailOutbox",
    "ExternalConnection",
    "ExternalConnectionCredential",
    "ExternalResource",
    "FinancialDaily",
    "FxRate",
    "Invitation",
    "JobRun",
    "Membership",
    "Order",
    "OrderItem",
    "Organization",
    "OrganizationResourceLink",
    "Product",
    "ProductCostHistory",
    "ProductVariant",
    "PromptVersion",
    "Refund",
    "RefundItem",
    "SalesEntry",
    "SecurityEvent",
    "Store",
    "User",
    "UserActionToken",
    "UserPasswordCredential",
    "UserSession",
    "WebhookEvent",
]
