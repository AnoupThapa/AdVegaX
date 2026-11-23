"""The authenticated caller (authentication result; carries no organization or role)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    session_id: uuid.UUID
    email: str
    display_name: str | None
    email_verified: bool
