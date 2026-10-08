"""Audit log API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: uuid.UUID
    actor_type: str
    actor_user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    result: str
    correlation_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    metadata: dict[str, Any]
    created_at: datetime
