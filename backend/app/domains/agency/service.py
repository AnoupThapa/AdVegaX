"""Agency grants and the clients list (Phase 14, tasks 14-01 … 14-04, PHASE_14_PLAN Q-14-1 …
Q-14-8; A33).

* An agency's owner or admin gets the **agency code** (random, can be replaced).
* A **client's owner** enters it with a role (manager, analyst or viewer): a **pending** grant.
* The agency's owner or admin **accepts** it: the grant is **active**, and the agency's members
  reach the client with the lower of their own role and the granted one (``access.py``).
* Either side's owner or admin **ends** it, at once; the grant stays in the history.

Every step is audited in **both** organizations and emailed to the other side's owners. The
clients list computes each client **on its own**, in its own currency — never a total.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound, ValidationFailed
from app.domains.agency.access import lower, names
from app.domains.agency.models import AgencyGrant
from app.domains.agency.schemas import AgencyOut, ClientOut, CodeOut, GrantIn, GrantOut
from app.domains.audit.service import Actor, record_audit
from app.domains.billing import entitlements
from app.domains.identity.models import User
from app.domains.integrations.models import ExternalConnection
from app.domains.metrics.read_service import MetricsReadService
from app.domains.optimization.models import Recommendation
from app.domains.organizations.models import Membership, Organization
from app.domains.organizations.permissions import Permission, authorize, has_permission
from app.domains.organizations.tenancy import TenantContext
from app.runtime import Runtime

logger = logging.getLogger("advegax.agency")

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I
CODE_LENGTH = 10
ROLE_TEXT = {"manager": "Manager", "analyst": "Analyst", "viewer": "Viewer"}


class AgencyDisabled(Conflict):
    message = "Agency mode is switched off for this AdVegaX installation."


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _owners(session: Session, org_id: uuid.UUID) -> list[str]:
    return list(
        session.execute(
            select(User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.organization_id == org_id,
                Membership.role == "owner",
                Membership.status == "active",
            )
            .order_by(User.email)
        ).scalars()
    )


class AgencyService:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    # ------------------------------------------------------------------ helpers
    def _on(self) -> None:
        if not self.rt.settings.AGENCY_ENABLED:
            raise AgencyDisabled()

    def _link(self, org_id: uuid.UUID, path: str = "/settings") -> str:
        return f"{self.rt.settings.APP_BASE_URL.rstrip('/')}/orgs/{org_id}{path}"

    def _out(self, grant: AgencyGrant, labels: dict[uuid.UUID, str]) -> GrantOut:
        return GrantOut(
            id=grant.id,
            client_id=grant.organization_id,
            client_name=labels.get(grant.organization_id),
            agency_id=grant.agency_organization_id,
            agency_name=labels.get(grant.agency_organization_id),
            role=grant.role,
            status=grant.status,
            created_at=grant.created_at,
            accepted_at=grant.accepted_at,
            revoked_at=grant.revoked_at,
        )

    def _record(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        grant: AgencyGrant,
        template: str | None = None,
        **values: Any,
    ) -> None:
        """Audit (and email the owners) in ``org_id``, in that organization's own context."""
        with self.rt.db.transaction(org_id=org_id) as session:
            record_audit(
                session,
                organization_id=org_id,
                actor=Actor.user(user_id),
                action=action,
                resource_type="agency_grant",
                resource_id=grant.id,
                after={
                    "client_id": grant.organization_id,
                    "agency_id": grant.agency_organization_id,
                    "role": grant.role,
                    "status": grant.status,
                },
            )
            if template is None:
                return
            org = session.get(Organization, org_id)
            for email in _owners(session, org_id):
                self.rt.notifications.send_email(
                    session,
                    template=template,
                    recipient=email,
                    organization_id=org_id,
                    variables={
                        "organization_name": org.name if org else "",
                        "link": self._link(org_id),
                        **values,
                    },
                )

    # ------------------------------------------------------------------ reading
    def get(self, ctx: TenantContext) -> AgencyOut:
        authorize(ctx, Permission.ORG_VIEW)
        enabled = self.rt.settings.AGENCY_ENABLED
        manage = has_permission(ctx.role, Permission.AGENCY_MANAGE) and not ctx.via_agency_id
        grant = has_permission(ctx.role, Permission.AGENCY_GRANT) and not ctx.via_agency_id
        if not enabled or ctx.via_agency_id is not None:
            return AgencyOut(
                enabled=enabled,
                code=None,
                can_grant=False,
                can_manage=False,
                agencies=[],
                clients=[],
            )
        org_id = ctx.organization_id
        with self.rt.db.transaction(org_id=org_id, user_id=ctx.user_id) as session:
            org = session.get(Organization, org_id)
            rows = list(
                session.execute(
                    select(AgencyGrant)
                    .where(
                        (AgencyGrant.organization_id == org_id)
                        | (AgencyGrant.agency_organization_id == org_id)
                    )
                    .order_by(AgencyGrant.created_at.desc())
                ).scalars()
            )
        labels = names(
            self.rt, {g.organization_id for g in rows} | {g.agency_organization_id for g in rows}
        )
        return AgencyOut(
            enabled=True,
            code=org.agency_code if org is not None and manage else None,
            can_grant=grant,
            can_manage=manage,
            agencies=[self._out(g, labels) for g in rows if g.organization_id == org_id],
            clients=[self._out(g, labels) for g in rows if g.agency_organization_id == org_id],
        )

    # ------------------------------------------------------------------ the agency code
    def new_code(self, ctx: TenantContext) -> CodeOut:
        """Owners and admins of the agency: a new code (the old one stops working; grants
        already made are not affected)."""
        self._on()
        authorize(ctx, Permission.AGENCY_MANAGE)
        for _ in range(5):
            code = _new_code()
            try:
                with self.rt.db.transaction(
                    org_id=ctx.organization_id, user_id=ctx.user_id
                ) as session:
                    org = session.get(Organization, ctx.organization_id, with_for_update=True)
                    if org is None:
                        raise NotFound()
                    org.agency_code = code
                    record_audit(
                        session,
                        organization_id=ctx.organization_id,
                        actor=Actor.user(ctx.user_id),
                        action="agency.code_changed",
                        resource_type="organization",
                        resource_id=ctx.organization_id,
                    )
                return CodeOut(code=code)
            except IntegrityError:
                continue  # pragma: no cover - a 32^10 collision
        raise Conflict()  # pragma: no cover

    # ------------------------------------------------------------------ the grant lifecycle
    def grant(self, ctx: TenantContext, body: GrantIn) -> GrantOut:
        """A client's owner gives the agency with ``code`` access, pending its acceptance."""
        self._on()
        authorize(ctx, Permission.AGENCY_GRANT)
        code = body.code.strip().upper()
        with self.rt.db.transaction(system=True) as session:
            found = session.execute(
                select(Organization.id, Organization.status).where(Organization.agency_code == code)
            ).first()
        if found is None or found.status != "active":
            raise ValidationFailed(details=[{"field": "code", "reason": "unknown_agency_code"}])
        agency_id = found.id
        if agency_id == ctx.organization_id:
            raise ValidationFailed(details=[{"field": "code", "reason": "own_code"}])
        try:
            with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
                grant = AgencyGrant(
                    organization_id=ctx.organization_id,
                    agency_organization_id=agency_id,
                    role=body.role,
                    status="pending",
                    granted_by_user_id=ctx.user_id,
                )
                session.add(grant)
                session.flush()
                session.refresh(grant)
        except IntegrityError:
            raise Conflict("This agency already has, or has been offered, access.") from None
        labels = names(self.rt, {ctx.organization_id, agency_id})
        self._record(ctx.organization_id, ctx.user_id, "agency.granted", grant)
        self._record(
            agency_id,
            ctx.user_id,
            "agency.offered",
            grant,
            "agency_offered",
            client_name=labels.get(ctx.organization_id, ""),
            role=ROLE_TEXT[grant.role],
        )
        return self._out(grant, labels)

    def _grant_for(self, session: Session, ctx: TenantContext, grant_id: uuid.UUID) -> AgencyGrant:
        grant = session.get(AgencyGrant, grant_id, with_for_update=True)
        if grant is None or ctx.organization_id not in (
            grant.organization_id,
            grant.agency_organization_id,
        ):
            raise NotFound()
        return grant

    def accept(self, ctx: TenantContext, grant_id: uuid.UUID) -> GrantOut:
        """The agency's owner or admin accepts a pending grant."""
        self._on()
        authorize(ctx, Permission.AGENCY_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            grant = self._grant_for(session, ctx, grant_id)
            if grant.agency_organization_id != ctx.organization_id:
                raise NotFound()  # only the agency side accepts
            if grant.status != "pending":
                raise Conflict("This access is not waiting to be accepted.")
            grant.status = "active"
            grant.accepted_by_user_id, grant.accepted_at = ctx.user_id, self.rt.clock.now()
        labels = names(self.rt, {grant.organization_id, grant.agency_organization_id})
        self._record(ctx.organization_id, ctx.user_id, "agency.accepted", grant)
        self._record(
            grant.organization_id,
            ctx.user_id,
            "agency.accepted",
            grant,
            "agency_accepted",
            agency_name=labels.get(grant.agency_organization_id, ""),
            role=ROLE_TEXT[grant.role],
        )
        return self._out(grant, labels)

    def revoke(self, ctx: TenantContext, grant_id: uuid.UUID) -> GrantOut:
        """Either side's owner or admin ends the access (or withdraws the offer), at once."""
        self._on()
        authorize(ctx, Permission.AGENCY_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            grant = self._grant_for(session, ctx, grant_id)
            if grant.status == "revoked":
                raise Conflict("This access has already ended.")
            grant.status = "revoked"
            grant.revoked_by_user_id, grant.revoked_at = ctx.user_id, self.rt.clock.now()
        labels = names(self.rt, {grant.organization_id, grant.agency_organization_id})
        other = (
            grant.agency_organization_id
            if ctx.organization_id == grant.organization_id
            else grant.organization_id
        )
        self._record(ctx.organization_id, ctx.user_id, "agency.ended", grant)
        self._record(
            other,
            ctx.user_id,
            "agency.ended",
            grant,
            "agency_ended",
            client_name=labels.get(grant.organization_id, ""),
            agency_name=labels.get(grant.agency_organization_id, ""),
        )
        return self._out(grant, labels)

    # ------------------------------------------------------------------ the clients list
    def clients(self, ctx: TenantContext) -> list[ClientOut]:
        """Each active client, computed on its own in its own context and currency."""
        self._on()
        authorize(ctx, Permission.ORG_VIEW)
        if ctx.via_agency_id is not None:
            raise NotFound()  # an agency's agency is not followed
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            grants = list(
                session.execute(
                    select(AgencyGrant)
                    .where(
                        AgencyGrant.agency_organization_id == ctx.organization_id,
                        AgencyGrant.status == "active",
                    )
                    .order_by(AgencyGrant.created_at)
                ).scalars()
            )
        metrics = MetricsReadService(self.rt)
        out: list[ClientOut] = []
        for grant in grants:
            client = TenantContext(
                organization_id=grant.organization_id,
                user_id=ctx.user_id,
                role=lower(grant.role, ctx.role),
                via_agency_id=ctx.organization_id,
            )
            with self.rt.db.transaction(org_id=client.organization_id) as session:
                org = session.get(Organization, client.organization_id)
                if org is None or org.status != "active":
                    continue
                status = entitlements.standing_of(self.rt, session, org.id).status
                open_advice = session.execute(
                    select(func.count())
                    .select_from(Recommendation)
                    .where(
                        Recommendation.organization_id == org.id,
                        Recommendation.status == "open",
                    )
                ).scalar_one()
                attention = session.execute(
                    select(func.count())
                    .select_from(ExternalConnection)
                    .where(
                        ExternalConnection.organization_id == org.id,
                        ExternalConnection.status.in_(("expired", "error")),
                    )
                ).scalar_one()
                name, currency = org.name, org.default_currency
            spend = sales = None
            try:
                overview = metrics.overview(client, from_day=None, to_day=None, store_id=None)
                spend = overview.totals.get("ad_spend")
                sales = overview.totals.get("net_sales")
                currency = overview.reporting_currency
            except AppError as exc:  # e.g. analytics not readable with this role
                logger.info("agency_client_figures_unavailable", extra={"error": exc.code})
            out.append(
                ClientOut(
                    organization_id=client.organization_id,
                    name=name,
                    role=client.role,
                    billing_status=status,
                    currency=currency,
                    ad_spend=spend,
                    net_sales=sales,
                    open_recommendations=int(open_advice),
                    connections_needing_attention=int(attention),
                )
            )
        return out
