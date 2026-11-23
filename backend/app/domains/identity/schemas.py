"""Identity API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.domains.identity.emails import normalize_email

Email = Annotated[str, Field(min_length=3, max_length=254), AfterValidator(normalize_email)]
Password = Annotated[str, Field(min_length=1, max_length=1024)]
Token = Annotated[str, Field(min_length=16, max_length=256)]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(_Request):
    email: Email
    password: Password
    display_name: Annotated[str, Field(min_length=1, max_length=120)] | None = None


class TokenRequest(_Request):
    token: Token


class LoginRequest(_Request):
    email: Email
    password: Password


class ForgotPasswordRequest(_Request):
    email: Email


class ResetPasswordRequest(_Request):
    token: Token
    new_password: Password


class ChangePasswordRequest(_Request):
    current_password: Password
    new_password: Password


class StatusOut(BaseModel):
    status: str


class CsrfOut(BaseModel):
    csrf_token: str


class CsrfStatusOut(StatusOut):
    csrf_token: str


class MembershipSummary(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    role: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    email_verified: bool
    memberships: list[MembershipSummary] = []


class LoginOut(BaseModel):
    user: UserOut
    csrf_token: str


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    auth_method: str
    user_agent_summary: str | None
    current: bool
