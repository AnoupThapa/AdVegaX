"""The Admin portal (Phase 16, tasks 16-03 and 16-05, PHASE_16_PLAN Q-16-4, Q-16-5; A35).

For the people who operate this installation — never customers. Every call needs a platform
admin; every call except setting up and entering the two-step code also needs that code
entered in this session (``ADMIN_STEP_UP_TTL``). Every change is audited (no organization).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, func, or_, select, text

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.request_meta import RequestMeta
from app.core.security.throttle import Limit
from app.core.settings import Settings
from app.domains.audit.service import Actor, record_audit
from app.domains.identity.models import User
from app.domains.identity.principal import Principal
from app.domains.organizations.models import Organization
from app.domains.platform import store, totp
from app.domains.platform.models import PlatformAdmin, PlatformSetting
from app.domains.platform.registry import BY_NAME, ENTRIES
from app.domains.platform.schemas import (
    AdminMeOut,
    AdminOrganizationOut,
    AdminUserOut,
    HealthOut,
    SettingOut,
    TotpSetupOut,
)
from app.runtime import Runtime

PENDING = "admin-totp-pending:{user}"
VERIFIED = "admin-verified:{session}"
# A code's time step once accepted, so the same code cannot be used again (QA-013).
USED = "admin-totp-used:{user}:{step}"
FIFTEEN_MINUTES = 15 * 60


class AdminRequired(Forbidden):
    code = "ADMIN_REQUIRED"
    message = "Only AdVegaX administrators can do this."


class AdminCodeRequired(Forbidden):
    code = "ADMIN_CODE_REQUIRED"
    message = "Enter the code from your authenticator app first."


class AdminService:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    # ------------------------------------------------------------------ who may
    def _admin(self, principal: Principal) -> PlatformAdmin:
        with self.rt.db.transaction(system=True) as session:
            admin = session.get(PlatformAdmin, principal.user_id)
        if admin is None:
            raise AdminRequired()
        return admin

    def _verified(self, principal: Principal) -> bool:
        return bool(self.rt.redis.exists(VERIFIED.format(session=principal.session_id)))

    def require(self, principal: Principal) -> PlatformAdmin:
        admin = self._admin(principal)
        if admin.totp_enabled_at is None or not self._verified(principal):
            raise AdminCodeRequired()
        return admin

    def _audit(self, principal: Principal, action: str, **after: object) -> None:
        with self.rt.db.transaction(user_id=principal.user_id) as session:
            record_audit(
                session,
                organization_id=None,
                actor=Actor.user(principal.user_id),
                action=action,
                resource_type="platform",
                resource_id=None,
                after=dict(after) or None,
            )

    # ------------------------------------------------------------------ two-step sign-in
    def me(self, principal: Principal) -> AdminMeOut:
        with self.rt.db.transaction(system=True) as session:
            admin = session.get(PlatformAdmin, principal.user_id)
        if admin is None:
            return AdminMeOut(is_admin=False, totp_enabled=False, verified=False)
        enabled = admin.totp_enabled_at is not None
        return AdminMeOut(
            is_admin=True, totp_enabled=enabled, verified=enabled and self._verified(principal)
        )

    def setup(self, principal: Principal) -> TotpSetupOut:
        admin = self._admin(principal)
        if admin.totp_enabled_at is not None:
            raise Conflict("Two-step sign-in is already on.")
        secret = totp.new_secret()
        self.rt.redis.set(
            PENDING.format(user=principal.user_id),
            secret,
            ex=int(self.rt.settings.ADMIN_STEP_UP_TTL.total_seconds()),
        )
        return TotpSetupOut(secret=secret, uri=totp.uri(secret, principal.email))

    def _check_code(
        self, principal: Principal, meta: RequestMeta, secret: str | None, code: str
    ) -> None:
        """Count the attempt (per person and per address), refuse a wrong or reused code and
        record failures in the audit log (QA-003, QA-013)."""
        s = self.rt.settings
        self.rt.throttler.hit(
            Limit("admin_code_user", s.THROTTLE_ADMIN_CODE_PER_USER_PER_15_MIN, FIFTEEN_MINUTES),
            str(principal.user_id),
        )
        self.rt.throttler.hit(
            Limit("admin_code_ip", s.THROTTLE_ADMIN_CODE_PER_IP_PER_15_MIN, FIFTEEN_MINUTES),
            meta.ip,
        )
        step = totp.match(secret, code, self.rt.clock.now()) if secret else None
        fresh = step is not None and bool(
            self.rt.redis.set(
                USED.format(user=principal.user_id, step=step),
                "1",
                nx=True,
                ex=totp.STEP * (2 * totp.WINDOW + 2),
            )
        )
        if not fresh:
            self._audit(principal, "platform.code_failed", reused=step is not None)
            raise ValidationFailed(details=[{"field": "code", "reason": "wrong_code"}])

    def enable(self, principal: Principal, code: str, meta: RequestMeta) -> AdminMeOut:
        self._admin(principal)
        pending = self.rt.redis.get(PENDING.format(user=principal.user_id))
        secret = pending.decode() if isinstance(pending, bytes) else pending
        self._check_code(principal, meta, str(secret) if secret else None, code)
        with self.rt.db.transaction(system=True) as session:
            admin = session.get(PlatformAdmin, principal.user_id, with_for_update=True)
            assert admin is not None
            store.seal_totp(self.rt.cipher, admin, str(secret))
            admin.totp_enabled_at = self.rt.clock.now()
        self.rt.redis.delete(PENDING.format(user=principal.user_id))
        self._mark(principal)
        self._audit(principal, "platform.two_step_on")
        return self.me(principal)

    def verify(self, principal: Principal, code: str, meta: RequestMeta) -> AdminMeOut:
        admin = self._admin(principal)
        secret = store.open_totp(self.rt.cipher, admin)
        self._check_code(principal, meta, secret, code)
        self._mark(principal)
        self._audit(principal, "platform.signed_in")
        return self.me(principal)

    def _mark(self, principal: Principal) -> None:
        self.rt.redis.set(
            VERIFIED.format(session=principal.session_id),
            "1",
            ex=int(self.rt.settings.ADMIN_STEP_UP_TTL.total_seconds()),
        )

    # ------------------------------------------------------------------ keys and switches
    def settings(self, principal: Principal) -> list[SettingOut]:
        self.require(principal)
        with self.rt.db.transaction(system=True) as session:
            rows = {r.name: r for r in session.execute(select(PlatformSetting)).scalars()}
        out = []
        file = self.rt.settings
        for e in ENTRIES:
            row = rows.get(e.name)
            current = getattr(file, e.name)
            in_file = e.name in file.model_fields_set
            if row is not None:
                source, is_set, hint, when = "portal", True, row.hint, row.updated_at
            else:
                source = "settings_file" if in_file else "default"
                is_set, when = current not in (None, "", False), None
                hint = _hint(e.kind, current)
            if e.kind == "secret" and hint:
                hint = f"••••{hint[-4:]}"
            if e.kind == "switch" and row is not None:
                hint = "on" if (row.hint or "").lower() in ("true", "1", "on") else "off"
            out.append(
                SettingOut(
                    name=e.name,
                    label=e.label,
                    group=e.group,
                    kind=e.kind,
                    source=source,
                    set=is_set,
                    hint=hint,
                    updated_at=when,
                )
            )
        return out

    def save(self, principal: Principal, name: str, value: str) -> list[SettingOut]:
        self.require(principal)
        entry = BY_NAME.get(name)
        if entry is None:
            raise NotFound()
        value = value.strip()
        if entry.kind == "switch":
            if value.lower() not in ("true", "false"):
                raise ValidationFailed(details=[{"field": "value", "reason": "on_or_off"}])
            value = value.lower()
        try:  # the value must be one the setting accepts
            Settings.model_validate({**self.rt.settings.model_dump(), name: value})
        except ValueError:
            raise ValidationFailed(details=[{"field": "value", "reason": "not_accepted"}]) from None
        with self.rt.db.transaction(system=True) as session:
            store.save(session, self.rt.cipher, name, value, principal.user_id)
        self.rt.redis.set("platform-settings:changed", "1")
        self._audit(principal, "platform.setting_saved", setting=name)  # never the value
        return self.settings(principal)

    def clear(self, principal: Principal, name: str) -> list[SettingOut]:
        self.require(principal)
        if name not in BY_NAME:
            raise NotFound()
        with self.rt.db.transaction(system=True) as session:
            row = session.get(PlatformSetting, name)
            if row is not None:
                session.delete(row)
        self.rt.redis.set("platform-settings:changed", "1")
        self._audit(principal, "platform.setting_cleared", setting=name)
        return self.settings(principal)

    # ------------------------------------------------------------------ organizations, people
    def organizations(
        self,
        principal: Principal,
        *,
        query: str = "",
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AdminOrganizationOut], int]:
        """One page of organizations by name, searched and filtered in the database (QA-011)."""
        self.require(principal)
        where: list[ColumnElement[bool]] = []
        if query.strip():
            where.append(Organization.name.ilike(f"%{_like(query.strip())}%", escape="\\"))
        if status:
            where.append(Organization.status == status)
        with self.rt.db.transaction(system=True) as session:
            total = session.execute(
                select(func.count()).select_from(Organization).where(*where)
            ).scalar_one()
            rows = session.execute(
                select(Organization.id, Organization.name, Organization.status)
                .where(*where)
                .order_by(Organization.name, Organization.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        return [AdminOrganizationOut(id=r.id, name=r.name, status=r.status) for r in rows], total

    def set_status(
        self, principal: Principal, org_id: uuid.UUID, status: str
    ) -> AdminOrganizationOut:
        self.require(principal)
        with self.rt.db.transaction(system=True) as session:
            found = session.execute(
                select(Organization.id).where(Organization.id == org_id)
            ).first()
            if found is None:
                raise NotFound()
            session.execute(
                text("UPDATE organizations SET status = :status WHERE id = :id"),
                {"status": status, "id": org_id},
            )
            row = session.execute(
                select(Organization.id, Organization.name, Organization.status).where(
                    Organization.id == org_id
                )
            ).one()
        self._audit(
            principal, "platform.organization_status", organization=str(org_id), status=status
        )
        return AdminOrganizationOut(id=row.id, name=row.name, status=row.status)

    def users(
        self,
        principal: Principal,
        *,
        query: str = "",
        sort: str = "newest",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AdminUserOut], int]:
        """One page of people, searched by email or name in the database (QA-011)."""
        self.require(principal)
        where: list[ColumnElement[bool]] = []
        if query.strip():
            pattern = f"%{_like(query.strip())}%"
            where.append(
                or_(
                    User.email.ilike(pattern, escape="\\"),
                    User.display_name.ilike(pattern, escape="\\"),
                )
            )
        order = (User.email, User.id) if sort == "email" else (User.created_at.desc(), User.id)
        with self.rt.db.transaction(system=True) as session:
            admins = set(session.execute(select(PlatformAdmin.user_id)).scalars())
            total = session.execute(
                select(func.count()).select_from(User).where(*where)
            ).scalar_one()
            rows = session.execute(
                select(User.id, User.email, User.display_name, User.status, User.created_at)
                .where(*where)
                .order_by(*order)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        people = [
            AdminUserOut(
                id=r.id,
                email=r.email,
                display_name=r.display_name,
                status=r.status,
                created_at=r.created_at,
                is_admin=r.id in admins,
            )
            for r in rows
        ]
        return people, total

    def health(self, principal: Principal) -> HealthOut:
        self.require(principal)
        database = redis_ok = False
        try:
            with self.rt.db.transaction(system=True) as session:
                session.execute(text("SELECT 1"))
                database = True
        except Exception:
            database = False
        try:
            redis_ok = bool(self.rt.redis.ping())
        except Exception:
            redis_ok = False
        switches = {
            e.name: bool(getattr(self.rt.settings, e.name)) for e in ENTRIES if e.kind == "switch"
        }
        counts = {}
        if database:
            with self.rt.db.transaction(system=True) as session:
                counts = {
                    "organizations_total": session.execute(
                        select(func.count()).select_from(Organization)
                    ).scalar_one(),
                    "organizations_active": session.execute(
                        select(func.count())
                        .select_from(Organization)
                        .where(Organization.status == "active")
                    ).scalar_one(),
                    "people_total": session.execute(
                        select(func.count()).select_from(User)
                    ).scalar_one(),
                    "administrators": session.execute(
                        select(func.count()).select_from(PlatformAdmin)
                    ).scalar_one(),
                }
        return HealthOut(
            **counts,
            database=database,
            redis=redis_ok,
            environment=str(self.rt.settings.ENVIRONMENT),
            switches=switches,
            restart_needed=bool(self.rt.redis.exists("platform-settings:changed")),
        )


def _like(text_: str) -> str:
    """Escape LIKE wildcards so a search for "50%" finds "50%" and nothing else."""
    return text_.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _hint(kind: str, value: object) -> str | None:
    if value in (None, ""):
        return None
    if kind == "switch":
        return "on" if value else "off"
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    return str(value)[-4:] if kind == "secret" else str(value)


def is_admin_user(rt: Runtime, user_id: uuid.UUID) -> bool:
    with rt.db.transaction(system=True) as session:
        return session.get(PlatformAdmin, user_id) is not None
