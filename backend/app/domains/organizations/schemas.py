"""Organization, membership and invitation API schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.domains.identity.schemas import Email

RoleName = Literal["owner", "admin", "manager", "analyst", "viewer"]
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _currency(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("Use a three-letter ISO 4217 currency code.")
    return value


def _timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Use an IANA time zone name, e.g. Australia/Sydney.") from None
    return value


def _slug(value: str) -> str:
    if not _SLUG.match(value):
        raise ValueError("Use lowercase letters, digits and single hyphens.")
    return value


Currency = Annotated[str, Field(min_length=3, max_length=3), AfterValidator(_currency)]
TimeZone = Annotated[str, Field(min_length=1, max_length=64), AfterValidator(_timezone)]
Slug = Annotated[str, Field(min_length=2, max_length=63), AfterValidator(_slug)]
Name = Annotated[str, Field(min_length=1, max_length=120)]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrganizationCreate(_Request):
    name: Name
    slug: Slug | None = None
    default_currency: Currency
    default_timezone: TimeZone


class OrganizationUpdate(_Request):
    name: Name | None = None
    default_currency: Currency | None = None
    default_timezone: TimeZone | None = None


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    default_currency: str
    default_timezone: str
    status: str
    role: str
    created_at: datetime
    # Phase 14: the agency's name when the person works here through its grant.
    via_agency: str | None = None


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str | None
    role: str
    status: str
    created_at: datetime


class MemberUpdate(_Request):
    role: RoleName | None = None
    status: Literal["active", "suspended"] | None = None


class InvitationCreate(_Request):
    email: Email
    role: RoleName


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime


class InvitationAccept(_Request):
    token: Annotated[str, Field(min_length=16, max_length=256)]
