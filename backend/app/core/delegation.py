"""Who is acting through an agency, for this request (Phase 14, Q-14-6).

The tenant check sets it when a person reaches an organization through an agency's grant;
``record_audit`` then adds ``via_agency_id`` to every record that person causes in that
organization, so the client sees which agency acted.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

# (client organization, agency organization)
_via: ContextVar[tuple[uuid.UUID, uuid.UUID] | None] = ContextVar("via_agency", default=None)


def set_via_agency(organization_id: uuid.UUID, agency_id: uuid.UUID | None) -> None:
    _via.set((organization_id, agency_id) if agency_id is not None else None)


def via_agency(organization_id: uuid.UUID | None) -> uuid.UUID | None:
    found = _via.get()
    if found is None or organization_id is None or found[0] != organization_id:
        return None
    return found[1]
