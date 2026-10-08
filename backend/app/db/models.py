"""Import every model so Alembic and tests see the full metadata."""

from app.db.base import Base
from app.domains.audit.models import AuditLog, SecurityEvent
from app.domains.identity.models import User, UserActionToken, UserPasswordCredential, UserSession
from app.domains.notifications.models import EmailOutbox
from app.domains.organizations.models import Invitation, Membership, Organization

__all__ = [
    "AuditLog",
    "Base",
    "EmailOutbox",
    "Invitation",
    "Membership",
    "Organization",
    "SecurityEvent",
    "User",
    "UserActionToken",
    "UserPasswordCredential",
    "UserSession",
]
