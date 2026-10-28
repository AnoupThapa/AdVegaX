"""Import every model so Alembic and tests see the full metadata."""

from app.db.base import Base
from app.domains.actions.models import Action, ActionEvent, ActionSettings
from app.domains.advertising.models import (
    Ad,
    AdAccount,
    AdBudget,
    AdCampaign,
    AdGroup,
    AdPerformanceDaily,
    AdSyncState,
)
from app.domains.agency.models import AgencyGrant
from app.domains.ai.models import AiModel, AiRun, CampaignStrategy, PromptVersion
from app.domains.analytics.models import AnalyticsDaily, AnalyticsProperty, AnalyticsSyncState
from app.domains.audit.models import AuditLog, SecurityEvent
from app.domains.autopilot.models import AutopilotPolicy, AutopilotRun
from app.domains.billing.models import BillingAccount, BillingEvent, BillingReconciliation
from app.domains.builder.models import CampaignDraft
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
from app.domains.creative.models import Creative, CreativeAsset, CreativeRules, CreativeSet
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
from app.domains.optimization.models import (
    OptimizationSettings,
    Recommendation,
    RecommendationOutcome,
)
from app.domains.organizations.models import Invitation, Membership, Organization
from app.domains.platform.models import PlatformAdmin, PlatformSetting
from app.domains.webhooks.models import WebhookEvent

__all__ = [
    "Action",
    "ActionEvent",
    "ActionSettings",
    "Ad",
    "AdAccount",
    "AdBudget",
    "AdCampaign",
    "AdGroup",
    "AdPerformanceDaily",
    "AdSyncState",
    "AgencyGrant",
    "AiModel",
    "AiRun",
    "AnalyticsDaily",
    "AnalyticsProperty",
    "AnalyticsSyncState",
    "AuditLog",
    "AutopilotPolicy",
    "AutopilotRun",
    "Base",
    "BillingAccount",
    "BillingEvent",
    "BillingReconciliation",
    "CampaignDraft",
    "CampaignStrategy",
    "CommerceSyncState",
    "Creative",
    "CreativeAsset",
    "CreativeRules",
    "CreativeSet",
    "EmailOutbox",
    "ExternalConnection",
    "ExternalConnectionCredential",
    "ExternalResource",
    "FinancialDaily",
    "FxRate",
    "Invitation",
    "JobRun",
    "Membership",
    "OptimizationSettings",
    "Order",
    "OrderItem",
    "Organization",
    "OrganizationResourceLink",
    "PlatformAdmin",
    "PlatformSetting",
    "Product",
    "ProductCostHistory",
    "ProductVariant",
    "PromptVersion",
    "Recommendation",
    "RecommendationOutcome",
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
