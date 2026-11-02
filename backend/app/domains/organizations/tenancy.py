"""Tenant context: the server-side result of authorization for one organization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    # Phase 14: set when the person works here through an agency's grant (the agency's id).
    via_agency_id: uuid.UUID | None = None
