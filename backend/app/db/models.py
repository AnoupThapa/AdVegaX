"""Import every model so Alembic and tests see the full metadata."""

from app.db.base import Base
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
    "AuditLog",
    "Base",
    "CommerceSyncState",
    "EmailOutbox",
    "ExternalConnection",
    "ExternalConnectionCredential",
    "ExternalResource",
    "FinancialDaily",
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
