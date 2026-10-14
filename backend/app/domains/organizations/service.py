"""Organizations, memberships and invitations (PHASE_01A_PLAN §11)."""

from __future__ import annotations

import re
import secrets
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound
from app.db.session import set_context
from app.domains.audit.service import Actor, record_audit
from app.domains.identity.models import User, UserActionToken
from app.domains.identity.principal import Principal
from app.domains.identity.service import IdentityService
from app.domains.notifications.service import humanize
from app.domains.organizations.models import Invitation, Membership, Organization
from app.domains.organizations.permissions import Permission, Role, authorize, can_assign, deny
from app.domains.organizations.schemas import (
    InvitationOut,
    MemberOut,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)
from app.domains.organizations.tenancy import TenantContext
from app.runtime import Runtime

SLUG_ATTEMPTS = 5


class LastOwner(Conflict):
    code = "LAST_OWNER"
    message = "An organization must keep at least one active owner."


class SlugTaken(Conflict):
    code = "SLUG_TAKEN"
    message = "That organization URL name is already taken."


class AlreadyMember(Conflict):
    code = "ALREADY_MEMBER"
    message = "This person is already a member of the organization."


class InvitationEmailMismatch(Forbidden):
    code = "INVITATION_EMAIL_MISMATCH"
    message = "This invitation was sent to a different email address."


class InvitationNotPending(Conflict):
    code = "INVITATION_NOT_PENDING"
    message = "This invitation is no longer pending."


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50].strip("-")
    return slug if len(slug) >= 2 else "org"


def _org_out(org: Organization, role: str) -> OrganizationOut:
    return OrganizationOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        default_currency=org.default_currency,
        default_timezone=org.default_timezone,
        status=org.status,
        role=role,
        created_at=org.created_at,
    )


def _org_snapshot(org: Organization) -> dict[str, Any]:
    return {
        "name": org.name,
        "default_currency": org.default_currency,
        "default_timezone": org.default_timezone,
    }


class OrganizationService:
    def __init__(self, runtime: Runtime, identity: IdentityService) -> None:
        self.rt = runtime
        self.identity = identity

    # -------------------------------------------------------------- tenancy
    def resolve_tenant(self, principal: Principal, organization_id: uuid.UUID) -> TenantContext:
        """Membership check for an organization claimed in the URL. Non-members get 404."""
        return self.tenant_for_user(principal.user_id, organization_id)

    def tenant_for_user(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> TenantContext:
        """The same check for a user named by server-side state (e.g. a connect flow whose
        last step arrives server to server, without the person's session — 2B-04)."""
        with self.rt.db.transaction(user_id=user_id) as session:
            membership = session.execute(
                select(Membership)
                .join(Organization, Organization.id == Membership.organization_id)
                .where(
                    Membership.organization_id == organization_id,
                    Membership.user_id == user_id,
                    Membership.status == "active",
                    Organization.status == "active",
                )
            ).scalar_one_or_none()
        if membership is None:
            raise NotFound()
        return TenantContext(organization_id=organization_id, user_id=user_id, role=membership.role)

    # -------------------------------------------------------------- organizations
    def create(self, principal: Principal, body: OrganizationCreate) -> OrganizationOut:
        for attempt in range(SLUG_ATTEMPTS):
            slug = body.slug or slugify(body.name)
            if body.slug is None and attempt > 0:
                slug = f"{slug[:45]}-{secrets.token_hex(3)}"
            try:
                return self._create(principal, body, slug)
            except IntegrityError as exc:
                if "uq_organizations_slug" not in str(exc.orig):
                    raise
                if body.slug is not None:
                    raise SlugTaken() from None
        raise SlugTaken()

    def _create(self, principal: Principal, body: OrganizationCreate, slug: str) -> OrganizationOut:
        org_id = uuid.uuid4()
        with self.rt.db.transaction(org_id=org_id, user_id=principal.user_id) as session:
            org = Organization(
                id=org_id,
                name=body.name,
                slug=slug,
                default_currency=body.default_currency,
                default_timezone=body.default_timezone,
                created_by_user_id=principal.user_id,
            )
            session.add(org)
            session.flush()
            membership = Membership(
                organization_id=org_id, user_id=principal.user_id, role=Role.OWNER
            )
            session.add(membership)
            session.flush()
            actor = Actor.user(principal.user_id)
            record_audit(
                session,
                organization_id=org_id,
                actor=actor,
                action="organization.created",
                resource_type="organization",
                resource_id=org_id,
                after={**_org_snapshot(org), "slug": slug},
            )
            record_audit(
                session,
                organization_id=org_id,
                actor=actor,
                action="membership.created",
                resource_type="membership",
                resource_id=membership.id,
                after={"user_id": principal.user_id, "role": Role.OWNER},
            )
            session.refresh(org)
            return _org_out(org, Role.OWNER)

    def list_for_user(self, principal: Principal) -> list[OrganizationOut]:
        with self.rt.db.transaction(user_id=principal.user_id) as session:
            rows = session.execute(
                select(Organization, Membership.role)
                .join(Membership, Membership.organization_id == Organization.id)
                .where(
                    Membership.user_id == principal.user_id,
                    Membership.status == "active",
                    Organization.status == "active",
                )
                .order_by(Organization.name)
            ).all()
            return [_org_out(org, role) for org, role in rows]

    def get(self, ctx: TenantContext) -> OrganizationOut:
        authorize(ctx, Permission.ORG_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            org = session.get(Organization, ctx.organization_id)
            if org is None:
                raise NotFound()
            return _org_out(org, ctx.role)

    def update(self, ctx: TenantContext, body: OrganizationUpdate) -> OrganizationOut:
        authorize(ctx, Permission.ORG_UPDATE)
        changes = body.model_dump(exclude_none=True)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            org = session.get(Organization, ctx.organization_id, with_for_update=True)
            if org is None:
                raise NotFound()
            before = _org_snapshot(org)
            for key, value in changes.items():
                setattr(org, key, value)
            if changes:
                org.updated_at = self.rt.clock.now()
                session.flush()
                record_audit(
                    session,
                    organization_id=org.id,
                    actor=Actor.user(ctx.user_id),
                    action="organization.updated",
                    resource_type="organization",
                    resource_id=org.id,
                    before=before,
                    after=_org_snapshot(org),
                )
            return _org_out(org, ctx.role)

    # -------------------------------------------------------------- members
    def list_members(self, ctx: TenantContext) -> list[MemberOut]:
        authorize(ctx, Permission.MEMBERS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            rows = session.execute(
                select(Membership, User)
                .join(User, User.id == Membership.user_id)
                .where(
                    Membership.organization_id == ctx.organization_id,
                    Membership.status != "removed",
                )
                .order_by(User.email)
            ).all()
            return [self._member_out(m, u) for m, u in rows]

    @staticmethod
    def _member_out(m: Membership, u: User) -> MemberOut:
        return MemberOut(
            id=m.id,
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=m.role,
            status=m.status,
            created_at=m.created_at,
        )

    def _lock_target(
        self, session: Session, ctx: TenantContext, member_id: uuid.UUID
    ) -> Membership:
        # Lock every active owner first (stable order) so concurrent demotions serialize.
        session.execute(
            select(Membership.id)
            .where(
                Membership.organization_id == ctx.organization_id,
                Membership.role == Role.OWNER,
                Membership.status == "active",
            )
            .order_by(Membership.id)
            .with_for_update()
        ).all()
        member = session.execute(
            select(Membership)
            .where(
                Membership.id == member_id,
                Membership.organization_id == ctx.organization_id,
                Membership.status != "removed",
            )
            .with_for_update()
        ).scalar_one_or_none()
        if member is None:
            raise NotFound()
        authorize(ctx, Permission.MEMBERS_MANAGE, member)
        return member

    def _active_owner_count(self, session: Session, org_id: uuid.UUID) -> int:
        return int(
            session.execute(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.organization_id == org_id,
                    Membership.role == Role.OWNER,
                    Membership.status == "active",
                )
            ).scalar_one()
        )

    def update_member(
        self, ctx: TenantContext, member_id: uuid.UUID, *, role: str | None, status: str | None
    ) -> MemberOut:
        authorize(ctx, Permission.MEMBERS_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            member = self._lock_target(session, ctx, member_id)
            if not can_assign(ctx.role, member.role) or (
                role is not None and not can_assign(ctx.role, role)
            ):
                deny(ctx, Permission.MEMBERS_ASSIGN_ROLE, "membership", member.id)
            before = {"role": member.role, "status": member.status}
            loses_owner = (
                member.role == Role.OWNER
                and member.status == "active"
                and (
                    (role is not None and role != Role.OWNER)
                    or (status is not None and status != "active")
                )
            )
            if loses_owner and self._active_owner_count(session, ctx.organization_id) <= 1:
                raise LastOwner()
            if role is not None:
                member.role = role
            if status is not None:
                member.status = status
            member.updated_at = self.rt.clock.now()
            session.flush()
            after = {"role": member.role, "status": member.status}
            if after != before:
                record_audit(
                    session,
                    organization_id=ctx.organization_id,
                    actor=Actor.user(ctx.user_id),
                    action="membership.updated",
                    resource_type="membership",
                    resource_id=member.id,
                    before=before,
                    after=after,
                )
            user = session.get(User, member.user_id)
            if user is None:  # pragma: no cover - FK guarantees the user exists
                raise NotFound()
            return self._member_out(member, user)

    def remove_member(self, ctx: TenantContext, member_id: uuid.UUID) -> None:
        authorize(ctx, Permission.MEMBERS_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            member = self._lock_target(session, ctx, member_id)
            if not can_assign(ctx.role, member.role):
                deny(ctx, Permission.MEMBERS_ASSIGN_ROLE, "membership", member.id)
            if (
                member.role == Role.OWNER
                and member.status == "active"
                and self._active_owner_count(session, ctx.organization_id) <= 1
            ):
                raise LastOwner()
            before = {"role": member.role, "status": member.status, "user_id": member.user_id}
            member.status = "removed"
            member.updated_at = self.rt.clock.now()
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="membership.removed",
                resource_type="membership",
                resource_id=member.id,
                before=before,
                after={"status": "removed"},
            )

    # -------------------------------------------------------------- invitations
    def _invitation_status(self, inv: Invitation) -> str:
        if inv.status == "pending" and inv.expires_at <= self.rt.clock.now():
            return "expired"
        return inv.status

    def _invitation_out(self, inv: Invitation) -> InvitationOut:
        return InvitationOut(
            id=inv.id,
            email=inv.email,
            role=inv.role,
            status=self._invitation_status(inv),
            expires_at=inv.expires_at,
            created_at=inv.created_at,
        )

    def _close_pending(self, session: Session, org_id: uuid.UUID, email: str, status: str) -> None:
        pending = (
            session.execute(
                select(Invitation)
                .where(
                    Invitation.organization_id == org_id,
                    Invitation.email == email,
                    Invitation.status == "pending",
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )
        now = self.rt.clock.now()
        for inv in pending:
            inv.status = "expired" if inv.expires_at <= now else status
            inv.updated_at = now
            session.execute(
                update(UserActionToken)
                .where(
                    UserActionToken.invitation_id == inv.id,
                    UserActionToken.consumed_at.is_(None),
                    UserActionToken.invalidated_at.is_(None),
                )
                .values(invalidated_at=now)
            )
        session.flush()

    def create_invitation(
        self, ctx: TenantContext, principal: Principal, *, email: str, role: str
    ) -> InvitationOut:
        authorize(ctx, Permission.MEMBERS_MANAGE)
        if not can_assign(ctx.role, role):
            deny(ctx, Permission.MEMBERS_ASSIGN_ROLE, "invitation")
        settings = self.rt.settings
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            existing = session.execute(
                select(Membership.id)
                .join(User, User.id == Membership.user_id)
                .where(
                    Membership.organization_id == ctx.organization_id,
                    User.email == email,
                    Membership.status == "active",
                )
            ).first()
            if existing is not None:
                raise AlreadyMember()
            self._close_pending(session, ctx.organization_id, email, "revoked")
            invitation = Invitation(
                organization_id=ctx.organization_id,
                email=email,
                role=role,
                invited_by_user_id=ctx.user_id,
                expires_at=self.rt.clock.now() + settings.INVITATION_TTL,
            )
            session.add(invitation)
            session.flush()
            raw = self.identity.issue_token(
                session,
                purpose="invitation",
                ttl=settings.INVITATION_TTL,
                email=email,
                organization_id=ctx.organization_id,
                invitation_id=invitation.id,
            )
            org = session.get(Organization, ctx.organization_id)
            if org is None:  # pragma: no cover - tenant context guarantees the organization
                raise NotFound()
            self.rt.notifications.send_email(
                session,
                template="invitation",
                recipient=email,
                organization_id=org.id,
                variables={
                    "organization_name": org.name,
                    "role": role,
                    "inviter_name": principal.display_name or principal.email,
                    "link": f"{settings.APP_BASE_URL.rstrip('/')}/invitations/accept#token={raw}",
                    "expires_in": humanize(settings.INVITATION_TTL),
                },
            )
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="invitation.created",
                resource_type="invitation",
                resource_id=invitation.id,
                after={"email": email, "role": role},
            )
            session.refresh(invitation)
            return self._invitation_out(invitation)

    def list_invitations(self, ctx: TenantContext) -> list[InvitationOut]:
        authorize(ctx, Permission.MEMBERS_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            rows = (
                session.execute(
                    select(Invitation)
                    .where(Invitation.organization_id == ctx.organization_id)
                    .order_by(Invitation.created_at.desc())
                )
                .scalars()
                .all()
            )
            return [self._invitation_out(i) for i in rows]

    def revoke_invitation(self, ctx: TenantContext, invitation_id: uuid.UUID) -> None:
        authorize(ctx, Permission.MEMBERS_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            inv = session.execute(
                select(Invitation)
                .where(
                    Invitation.id == invitation_id,
                    Invitation.organization_id == ctx.organization_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if inv is None:
                raise NotFound()
            authorize(ctx, Permission.MEMBERS_MANAGE, inv)
            if inv.status != "pending":
                raise InvitationNotPending()
            self._close_pending(session, ctx.organization_id, inv.email, "revoked")
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="invitation.revoked",
                resource_type="invitation",
                resource_id=inv.id,
                before={"status": "pending"},
                after={"status": "revoked"},
            )

    def accept_invitation(self, principal: Principal, token: str) -> OrganizationOut:
        now = self.rt.clock.now()
        with self.rt.db.transaction(user_id=principal.user_id) as session:
            record = self.identity.consume_token(session, token, "invitation")
            if record.organization_id is None or record.invitation_id is None:  # pragma: no cover
                raise NotFound()
            # The organization comes from a server-validated single-use token, never the client.
            set_context(session, org_id=record.organization_id, user_id=principal.user_id)
            inv = session.execute(
                select(Invitation).where(Invitation.id == record.invitation_id).with_for_update()
            ).scalar_one_or_none()
            if inv is None or inv.status != "pending" or inv.expires_at <= now:
                raise InvitationNotPending()
            if inv.email != principal.email:
                raise InvitationEmailMismatch()
            membership = session.execute(
                select(Membership)
                .where(
                    Membership.organization_id == inv.organization_id,
                    Membership.user_id == principal.user_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            actor = Actor.user(principal.user_id)
            if membership is None:
                membership = Membership(
                    organization_id=inv.organization_id, user_id=principal.user_id, role=inv.role
                )
                session.add(membership)
                session.flush()
                action = "membership.created"
            elif membership.status != "active":
                membership.status, membership.role, membership.updated_at = "active", inv.role, now
                action = "membership.reactivated"
            else:
                action = "membership.unchanged"
            inv.status, inv.accepted_at, inv.accepted_by_user_id, inv.updated_at = (
                "accepted",
                now,
                principal.user_id,
                now,
            )
            record_audit(
                session,
                organization_id=inv.organization_id,
                actor=actor,
                action="invitation.accepted",
                resource_type="invitation",
                resource_id=inv.id,
                after={"user_id": principal.user_id},
            )
            if action != "membership.unchanged":
                record_audit(
                    session,
                    organization_id=inv.organization_id,
                    actor=actor,
                    action=action,
                    resource_type="membership",
                    resource_id=membership.id,
                    after={"user_id": principal.user_id, "role": membership.role},
                )
            org = session.get(Organization, inv.organization_id)
            if org is None:  # pragma: no cover
                raise NotFound()
            return _org_out(org, membership.role)
