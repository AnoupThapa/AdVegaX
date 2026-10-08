"""Central, deny-by-default organization-level authorization (A7, API §24).

Four separated concerns (ARCHITECTURE §8): membership → organization role →
resource ownership/linking → future resource-level grants. ``authorize`` already
receives the resource so per-resource grants can be added without redesign.
"""

from __future__ import annotations

import logging
import uuid
from enum import StrEnum
from typing import Protocol

from app.core.errors import Forbidden, NotFound
from app.domains.organizations.tenancy import TenantContext

logger = logging.getLogger("advegax.authz")


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    ANALYST = "analyst"
    VIEWER = "viewer"


ROLE_RANK: dict[str, int] = {
    Role.OWNER: 5,
    Role.ADMIN: 4,
    Role.MANAGER: 3,
    Role.ANALYST: 2,
    Role.VIEWER: 1,
}


class Permission(StrEnum):
    ORG_VIEW = "organization.view"
    ORG_UPDATE = "organization.update"
    MEMBERS_VIEW = "members.view"
    MEMBERS_MANAGE = "members.manage"
    AUDIT_VIEW = "audit.view"


_ALL = frozenset(Role)
_OWNER_ADMIN = frozenset({Role.OWNER, Role.ADMIN})

PERMISSION_MATRIX: dict[Permission, frozenset[Role]] = {
    Permission.ORG_VIEW: _ALL,
    Permission.ORG_UPDATE: _OWNER_ADMIN,
    Permission.MEMBERS_VIEW: _ALL,
    Permission.MEMBERS_MANAGE: _OWNER_ADMIN,
    Permission.AUDIT_VIEW: _OWNER_ADMIN,
}


class TenantResource(Protocol):
    @property
    def organization_id(self) -> uuid.UUID: ...


def has_permission(role: str, permission: Permission) -> bool:
    return role in PERMISSION_MATRIX.get(permission, frozenset())


def authorize(
    ctx: TenantContext, permission: Permission, resource: TenantResource | None = None
) -> None:
    """Raise unless the caller may perform ``permission`` (on ``resource``) in this tenant."""
    if resource is not None and resource.organization_id != ctx.organization_id:
        # Defence in depth: a resource from another tenant is never acknowledged.
        raise NotFound()
    if not has_permission(ctx.role, permission):
        logger.warning(
            "authorization_denied",
            extra={
                "organization_id": str(ctx.organization_id),
                "user_id": str(ctx.user_id),
                "permission": permission.value,
                "role": ctx.role,
            },
        )
        raise Forbidden()


def can_assign(actor_role: str, target_role: str) -> bool:
    """Only owners grant or remove the owner role; nobody assigns above their own rank."""
    if target_role == Role.OWNER:
        return actor_role == Role.OWNER
    return ROLE_RANK[actor_role] >= ROLE_RANK[target_role]
