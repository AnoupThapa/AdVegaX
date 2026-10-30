"""The Admin portal (Phase 16, tasks 16-03 and 16-05, PHASE_16_PLAN Q-16-4, Q-16-5; A35).

For the people who operate this installation — never customers. Every call needs a platform
admin; every call except setting up and entering the two-step code also needs that code
entered in this session (``ADMIN_STEP_UP_TTL``). Every change is audited (no organization).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
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

    def enable(self, principal: Principal, code: str) -> AdminMeOut:
        self._admin(principal)
        pending = self.rt.redis.get(PENDING.format(user=principal.user_id))
        secret = pending.decode() if isinstance(pending, bytes) else pending
        if not secret or not totp.verify(str(secret), code, self.rt.clock.now()):
            raise ValidationFailed(details=[{"field": "code", "reason": "wrong_code"}])
        with self.rt.db.transaction(system=True) as session:
            admin = session.get(PlatformAdmin, principal.user_id, with_for_update=True)
            assert admin is not None
            store.seal_totp(self.rt.cipher, admin, str(secret))
            admin.totp_enabled_at = self.rt.clock.now()
        self.rt.redis.delete(PENDING.format(user=principal.user_id))
        self._mark(principal)
        self._audit(principal, "platform.two_step_on")
        return self.me(principal)

    def verify(self, principal: Principal, code: str) -> AdminMeOut:
        admin = self._admin(principal)
        secret = store.open_totp(self.rt.cipher, admin)
        if secret is None or not totp.verify(secret, code, self.rt.clock.now()):
            raise ValidationFailed(details=[{"field": "code", "reason": "wrong_code"}])
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
    def organizations(self, principal: Principal) -> list[AdminOrganizationOut]:
        self.require(principal)
        with self.rt.db.transaction(system=True) as session:
            rows = session.execute(
                select(Organization.id, Organization.name, Organization.status).order_by(
                    Organization.name
                )
            ).all()
        return [AdminOrganizationOut(id=r.id, name=r.name, status=r.status) for r in rows]

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

    def users(self, principal: Principal) -> list[AdminUserOut]:
        self.require(principal)
        with self.rt.db.transaction(system=True) as session:
            admins = set(session.execute(select(PlatformAdmin.user_id)).scalars())
            rows = session.execute(
                select(User.id, User.email, User.display_name, User.status, User.created_at)
                .order_by(User.created_at.desc())
                .limit(500)
            ).all()
        return [
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
        return HealthOut(
            database=database,
            redis=redis_ok,
            environment=str(self.rt.settings.ENVIRONMENT),
            switches=switches,
            restart_needed=bool(self.rt.redis.exists("platform-settings:changed")),
        )


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
