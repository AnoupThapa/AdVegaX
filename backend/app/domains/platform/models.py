"""The Admin portal's records (Phase 16; A35). System role only."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TZ = DateTime(timezone=True)


class PlatformAdmin(Base):
    __tablename__ = "platform_admins"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    totp_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_wrapped_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_key_version: Mapped[int | None] = mapped_column(Integer)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    hint: Mapped[str | None] = mapped_column(String(8))  # last 4 of a secret; the switch value
    updated_by: Mapped[uuid.UUID | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
