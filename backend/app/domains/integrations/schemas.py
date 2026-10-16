"""Connection, resource and job API schemas. Credentials never appear here (A16)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProviderOut(BaseModel):
    """A platform the web app may offer for connection. Public metadata only — never secrets."""

    code: str
    display_name: str
    category: str
    auth_scheme: str
    capabilities: dict[str, bool]
    test_only: bool


class AuthorizationStartIn(BaseModel):
    """Optional connect parameters, e.g. ``{"params": {"shop_domain": "eve-zone"}}`` for Shopify.

    Each provider validates its own parameters; unknown keys are refused.
    """

    params: dict[str, str] = Field(default_factory=dict, max_length=5)


class AuthorizationStartOut(BaseModel):
    authorize_url: str
    expires_in_seconds: int


class ConnectionOut(BaseModel):
    id: uuid.UUID
    provider: str
    auth_scheme: str
    status: str
    authorized_by_user_id: uuid.UUID | None
    granted_scopes: list[str]
    account_label: str | None
    last_error_code: str | None
    created_at: datetime
    revoked_at: datetime | None


class ResourceOut(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    provider: str
    kind: str
    external_id: str
    display_name: str | None
    currency: str | None
    timezone: str | None
    accessible: bool
    # Phase 3: why it cannot be linked (a plain message key, e.g. ``manager_account`` or
    # ``account_not_enabled``) and the groups it sits in (e.g. "Agency > Retail clients").
    unavailable_reason: str | None = None
    group_path: str | None = None
    capabilities: dict[str, bool]
    linked: bool
    link_id: uuid.UUID | None
    discovered_at: datetime
    last_synced_at: datetime | None


class LinkOut(BaseModel):
    id: uuid.UUID
    resource_id: uuid.UUID
    status: str
    linked_at: datetime
    unlinked_at: datetime | None
    unlink_reason: str | None


class JobOut(BaseModel):
    id: uuid.UUID
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    last_error_code: str | None
