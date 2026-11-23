"""How a person reaches a client organization through an agency (Phase 14, task 14-02,
PHASE_14_PLAN Q-14-2 … Q-14-4; A33).

A member of an agency organization works in a client organization when the client's grant to
that agency is **active**. Their role there is the **lower** of their role in the agency and
the role the client granted (manager, analyst or viewer — never owner or admin). Checked on
every request, so ending a grant takes effect at once. Everything they then read or change
happens in the **client's** tenant context, exactly as for its own members.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.domains.agency.models import AgencyGrant
from app.domains.organizations.models import Membership, Organization
from app.domains.organizations.permissions import ROLE_RANK
from app.domains.organizations.schemas import OrganizationOut
from app.runtime import Runtime


def lower(a: str, b: str) -> str:
    return a if ROLE_RANK[a] <= ROLE_RANK[b] else b


def _grants(rt: Runtime, user_id: uuid.UUID, client: uuid.UUID | None) -> list[Any]:
    with rt.db.transaction(user_id=user_id) as session:
        query = (
            select(
                AgencyGrant.organization_id,
                AgencyGrant.agency_organization_id,
                AgencyGrant.role,
                Membership.role,
            )
            .join(
                Membership,
                Membership.organization_id == AgencyGrant.agency_organization_id,
            )
            .join(Organization, Organization.id == AgencyGrant.agency_organization_id)
            .where(
                AgencyGrant.status == "active",
                Membership.user_id == user_id,
                Membership.status == "active",
                Organization.status == "active",
            )
            .order_by(AgencyGrant.created_at)
        )
        if client is not None:
            query = query.where(AgencyGrant.organization_id == client)
        return list(session.execute(query).all())


def delegated_role(
    rt: Runtime, user_id: uuid.UUID, client: uuid.UUID
) -> tuple[str, uuid.UUID] | None:
    """(effective role, agency id) when ``user_id`` may work in ``client`` through an agency."""
    rows = _grants(rt, user_id, client)
    if not rows:
        return None
    with rt.db.transaction(org_id=client) as session:
        org = session.get(Organization, client)
        if org is None or org.status != "active":
            return None
    # Several agencies of the same person: the highest role any of them gives.
    best = max(rows, key=lambda r: ROLE_RANK[lower(r.role, r[3])])
    return lower(best.role, best[3]), best.agency_organization_id


def names(rt: Runtime, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Organization names for the other side of a grant (the system role's narrow read)."""
    if not ids:
        return {}
    with rt.db.transaction(system=True) as session:
        rows = session.execute(
            select(Organization.id, Organization.name).where(Organization.id.in_(ids))
        ).all()
    return {r.id: r.name for r in rows}


def client_organizations(rt: Runtime, user_id: uuid.UUID) -> list[OrganizationOut]:
    """The client organizations a person reaches through their agencies, for the switcher."""
    with rt.db.transaction(user_id=user_id) as session:
        own = set(
            session.execute(
                select(Membership.organization_id).where(
                    Membership.user_id == user_id, Membership.status == "active"
                )
            ).scalars()
        )
    clients = sorted({r.organization_id for r in _grants(rt, user_id, None)} - own)
    out: list[OrganizationOut] = []
    for client in clients:
        found = delegated_role(rt, user_id, client)
        if found is None:
            continue
        role, agency = found
        with rt.db.transaction(org_id=client) as session:
            org = session.get(Organization, client)
            assert org is not None
            out.append(
                OrganizationOut(
                    id=org.id,
                    name=org.name,
                    slug=org.slug,
                    default_currency=org.default_currency,
                    default_timezone=org.default_timezone,
                    status=org.status,
                    role=role,
                    created_at=org.created_at,
                    via_agency=names(rt, {agency}).get(agency),
                )
            )
    return sorted(out, key=lambda o: o.name)
