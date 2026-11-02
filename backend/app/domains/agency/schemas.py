"""Agency API schemas (Phase 14, task 14-03; API_SPECIFICATION §19O)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domains.commerce.schemas import FigureOut

GrantRole = Literal["manager", "analyst", "viewer"]


class GrantIn(BaseModel):
    code: str = Field(min_length=6, max_length=32)  # the agency's code
    role: GrantRole = "manager"


class GrantOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    client_name: str | None
    agency_id: uuid.UUID
    agency_name: str | None
    role: GrantRole
    status: Literal["pending", "active", "revoked"]
    created_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class AgencyOut(BaseModel):
    enabled: bool  # AGENCY_ENABLED
    code: str | None  # this organization's agency code (owners and admins only)
    can_grant: bool  # an owner may give an agency access
    can_manage: bool  # owners and admins accept and end access
    agencies: list[GrantOut]  # agencies with access to this organization
    clients: list[GrantOut]  # organizations that gave this one access


class CodeOut(BaseModel):
    code: str


class ClientOut(BaseModel):
    organization_id: uuid.UUID
    name: str
    role: str  # your role there
    billing_status: str
    currency: str  # the client's own reporting currency — never converted across clients
    ad_spend: FigureOut | None  # None: could not be computed
    net_sales: FigureOut | None
    open_recommendations: int
    connections_needing_attention: int
