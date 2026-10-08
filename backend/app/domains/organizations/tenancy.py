"""Tenant context: the server-side result of authorization for one organization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: str
