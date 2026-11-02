"""Admin portal API schemas (Phase 16, task 16-05; API_SPECIFICATION §19P)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AdminMeOut(BaseModel):
    is_admin: bool
    totp_enabled: bool
    verified: bool  # two-step sign-in done for this session


class TotpSetupOut(BaseModel):
    secret: str  # typed into an authenticator app (shown once, before it is switched on)
    uri: str  # otpauth:// link


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class SettingOut(BaseModel):
    name: str
    label: str
    group: str
    kind: Literal["secret", "text", "switch"]
    source: Literal["portal", "settings_file", "default"]
    set: bool
    hint: str | None  # secret: "••••1234"; text: the value; switch: "on" / "off"
    updated_at: datetime | None


class SettingIn(BaseModel):
    value: str = Field(min_length=1, max_length=8000)


class AdminOrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    status: str
    created_at: datetime
    is_admin: bool


class StatusIn(BaseModel):
    status: Literal["active", "suspended"]


class HealthOut(BaseModel):
    database: bool
    redis: bool
    environment: str
    switches: dict[str, bool]
    restart_needed: bool  # a value saved since AdVegaX started
