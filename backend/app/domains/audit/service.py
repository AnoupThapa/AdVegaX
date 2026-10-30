"""Audit trail and security events (MASTER §13). Inserts only; secrets are scrubbed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.core.correlation import get_correlation_id
from app.core.delegation import via_agency
from app.core.logging import scrub
from app.core.request_meta import RequestMeta
from app.core.security.tokens import keyed_hash
from app.domains.audit.models import AuditLog, SecurityEvent


@dataclass(frozen=True)
class Actor:
    type: str
    user_id: uuid.UUID | None

    @classmethod
    def user(cls, user_id: uuid.UUID) -> Actor:
        return cls("user", user_id)


def _clean(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    cleaned = scrub(value)
    if not isinstance(cleaned, dict):  # pragma: no cover - scrub preserves dicts
        raise TypeError("audit payload must be a mapping")
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in cleaned.items()}


def _with_agency(
    organization_id: uuid.UUID | None, actor: Actor, metadata: dict[str, Any] | None
) -> dict[str, Any] | None:
    agency = via_agency(organization_id) if actor.type == "user" else None
    if agency is None:
        return metadata
    return {**(metadata or {}), "via_agency_id": str(agency)}


def record_audit(
    session: Session,
    *,
    organization_id: uuid.UUID | None,
    actor: Actor,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str | None,
    result: str = "success",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.execute(
        insert(AuditLog).values(
            id=uuid.uuid4(),
            organization_id=organization_id,
            actor_type=actor.type,
            actor_user_id=actor.user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            result=result,
            correlation_id=get_correlation_id(),
            before_json=_clean(before),
            after_json=_clean(after),
            metadata_json=_clean(_with_agency(organization_id, actor, metadata)) or {},
        )
    )


def record_security_event(
    session: Session,
    *,
    event_type: str,
    secret: str,
    meta: RequestMeta | None,
    user_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.execute(
        insert(SecurityEvent).values(
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            event_type=event_type,
            ip_hash=keyed_hash(secret, meta.ip) if meta else None,
            user_agent_summary=meta.user_agent if meta else None,
            correlation_id=get_correlation_id(),
            metadata_json=_clean(metadata) or {},
        )
    )
