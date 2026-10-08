"""Identity domain: registration, verification, sessions and passwords (PHASE_01A_PLAN §9).

Authentication only — organization authorization lives in the organizations domain.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import InvalidCredentials, InvalidToken, ValidationFailed
from app.core.request_meta import RequestMeta
from app.core.security.passwords import (
    hash_password,
    password_policy_errors,
    verify_dummy,
    verify_password,
)
from app.core.security.throttle import Limit
from app.core.security.tokens import generate_token, hash_token, keyed_hash
from app.domains.audit.service import record_security_event
from app.domains.identity.models import User, UserActionToken, UserPasswordCredential, UserSession
from app.domains.identity.principal import Principal
from app.domains.identity.schemas import MembershipSummary, SessionOut, UserOut
from app.domains.notifications.service import humanize
from app.domains.organizations.models import Membership, Organization
from app.runtime import Runtime

MINUTE = 60
HOUR = 3600


class IdentityService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime
        self.settings = runtime.settings

    # ------------------------------------------------------------------ helpers
    @property
    def _secret(self) -> str:
        return self.settings.SECRET_KEY.get_secret_value()

    def _now(self) -> datetime:
        return self.rt.clock.now()

    def _link(self, path: str, token: str | None = None) -> str:
        base = self.settings.APP_BASE_URL.rstrip("/")
        return f"{base}{path}#token={token}" if token else f"{base}{path}"

    def _event(
        self,
        session: Session,
        event_type: str,
        meta: RequestMeta | None,
        user_id: uuid.UUID | None = None,
        **metadata: object,
    ) -> None:
        record_security_event(
            session,
            event_type=event_type,
            secret=self._secret,
            meta=meta,
            user_id=user_id,
            metadata=dict(metadata) or None,
        )

    def _check_password_policy(self, password: str, email: str) -> None:
        errors = password_policy_errors(
            password,
            email=email,
            min_length=self.settings.PASSWORD_MIN_LENGTH,
            max_length=self.settings.PASSWORD_MAX_LENGTH,
        )
        if errors:
            raise ValidationFailed(
                details=[
                    {"location": ["body", "password"], "message": e, "type": "password_policy"}
                    for e in errors
                ]
            )

    def _throttle_email_action(self, email: str, meta: RequestMeta) -> None:
        s = self.settings
        self.rt.throttler.hit(
            Limit("email_action_ip", s.THROTTLE_EMAIL_ACTION_PER_IP_PER_HOUR, HOUR), meta.ip
        )
        self.rt.throttler.hit(
            Limit("email_action_email", s.THROTTLE_EMAIL_ACTION_PER_EMAIL_PER_HOUR, HOUR), email
        )

    def issue_token(
        self,
        session: Session,
        *,
        purpose: str,
        ttl: timedelta,
        user_id: uuid.UUID | None = None,
        email: str | None = None,
        organization_id: uuid.UUID | None = None,
        invitation_id: uuid.UUID | None = None,
    ) -> str:
        """Create a single-use token; earlier unused tokens with the same scope are invalidated."""
        now = self._now()
        scope = (
            UserActionToken.invitation_id == invitation_id
            if invitation_id
            else (UserActionToken.user_id == user_id)
        )
        session.execute(
            update(UserActionToken)
            .where(
                UserActionToken.purpose == purpose,
                scope,
                UserActionToken.consumed_at.is_(None),
                UserActionToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
        )
        raw = generate_token()
        session.add(
            UserActionToken(
                purpose=purpose,
                token_hash=hash_token(raw),
                user_id=user_id,
                email=email,
                organization_id=organization_id,
                invitation_id=invitation_id,
                expires_at=now + ttl,
                created_at=now,
            )
        )
        return raw

    def consume_token(self, session: Session, raw: str, purpose: str) -> UserActionToken:
        token = session.execute(
            select(UserActionToken)
            .where(
                UserActionToken.token_hash == hash_token(raw), UserActionToken.purpose == purpose
            )
            .with_for_update()
        ).scalar_one_or_none()
        now = self._now()
        if (
            token is None
            or token.consumed_at is not None
            or token.invalidated_at is not None
            or token.expires_at <= now
        ):
            raise InvalidToken()
        token.consumed_at = now
        return token

    def _create_session(self, session: Session, user_id: uuid.UUID, meta: RequestMeta) -> str:
        now = self._now()
        absolute = now + self.settings.SESSION_ABSOLUTE_TIMEOUT
        raw = generate_token()
        session.add(
            UserSession(
                user_id=user_id,
                token_hash=hash_token(raw),
                created_at=now,
                last_used_at=now,
                idle_expires_at=min(now + self.settings.SESSION_IDLE_TIMEOUT, absolute),
                absolute_expires_at=absolute,
                ip_hash=keyed_hash(self._secret, meta.ip),
                user_agent_summary=meta.user_agent,
            )
        )
        return raw

    def _revoke_sessions(
        self, session: Session, user_id: uuid.UUID, reason: str, *, only: uuid.UUID | None = None
    ) -> None:
        stmt = update(UserSession).where(
            UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
        )
        if only is not None:
            stmt = stmt.where(UserSession.id == only)
        session.execute(stmt.values(revoked_at=self._now(), revoked_reason=reason))

    def _queue_verification(self, session: Session, user: User) -> None:
        raw = self.issue_token(
            session,
            purpose="email_verification",
            ttl=self.settings.EMAIL_VERIFICATION_TTL,
            user_id=user.id,
            email=user.email,
        )
        self.rt.notifications.send_email(
            session,
            template="email_verification",
            recipient=user.email,
            variables={
                "name": user.display_name or "",
                "link": self._link("/verify-email", raw),
                "expires_in": humanize(self.settings.EMAIL_VERIFICATION_TTL),
            },
        )

    # ------------------------------------------------------------ registration
    def register(
        self, *, email: str, password: str, display_name: str | None, meta: RequestMeta
    ) -> None:
        s = self.settings
        self.rt.throttler.hit(
            Limit("register_ip", s.THROTTLE_REGISTER_PER_IP_PER_HOUR, HOUR), meta.ip
        )
        self._check_password_policy(password, email)
        password_hash = hash_password(password)  # always computed: equal work for new/existing
        with self.rt.db.transaction() as session:
            existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if existing is not None:
                self._throttle_email_action(email, meta)
                self.rt.notifications.send_email(
                    session,
                    template="account_exists",
                    recipient=email,
                    variables={
                        "sign_in_link": self._link("/sign-in"),
                        "reset_link": self._link("/forgot-password"),
                    },
                )
                self._event(session, "registration_existing_email", meta, existing.id)
                return
            user = User(email=email, display_name=display_name)
            session.add(user)
            session.flush()
            session.add(UserPasswordCredential(user_id=user.id, password_hash=password_hash))
            self._queue_verification(session, user)
            self._event(session, "user_registered", meta, user.id)

    def verify_email(self, *, token: str, meta: RequestMeta) -> None:
        with self.rt.db.transaction() as session:
            record = self.consume_token(session, token, "email_verification")
            user = (
                session.get(User, record.user_id, with_for_update=True) if record.user_id else None
            )
            if user is None or user.email != record.email:
                raise InvalidToken()
            if user.email_verified_at is None:
                user.email_verified_at = self._now()
                user.updated_at = self._now()
            self._event(session, "email_verified", meta, user.id)

    def resend_verification(self, principal: Principal, meta: RequestMeta) -> None:
        if principal.email_verified:
            return
        self._throttle_email_action(principal.email, meta)
        with self.rt.db.transaction(user_id=principal.user_id) as session:
            user = session.get(User, principal.user_id)
            if user is None or user.email_verified_at is not None:
                return
            self._queue_verification(session, user)
            self._event(session, "email_verification_resent", meta, user.id)

    # ------------------------------------------------------------------ sessions
    def login(
        self, *, email: str, password: str, meta: RequestMeta, previous_session_token: str | None
    ) -> str:
        s = self.settings
        self.rt.throttler.hit(
            Limit("login_ip", s.THROTTLE_LOGIN_PER_IP_PER_MINUTE, MINUTE), meta.ip
        )
        self.rt.throttler.hit(
            Limit("login_account_ip", s.THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE, MINUTE),
            f"{email}|{meta.ip}",
        )
        with self.rt.db.transaction() as session:
            row = session.execute(
                select(User, UserPasswordCredential)
                .join(UserPasswordCredential, UserPasswordCredential.user_id == User.id)
                .where(User.email == email)
            ).one_or_none()
            if row is None:
                verify_dummy(password)
                self._event(session, "login_failed", meta, reason="unknown_account")
            else:
                user, credential = row
                check = verify_password(credential.password_hash, password)
                if check.valid and user.status == "active":
                    if check.needs_rehash:
                        credential.password_hash = hash_password(password)
                    if previous_session_token:
                        session.execute(
                            update(UserSession)
                            .where(
                                UserSession.token_hash == hash_token(previous_session_token),
                                UserSession.user_id == user.id,
                                UserSession.revoked_at.is_(None),
                            )
                            .values(revoked_at=self._now(), revoked_reason="rotated")
                        )
                    token = self._create_session(session, user.id, meta)
                    self._event(session, "login_succeeded", meta, user.id)
                    return token
                self._event(
                    session,
                    "login_failed",
                    meta,
                    user.id,
                    reason="bad_password" if not check.valid else "account_disabled",
                )
        raise InvalidCredentials()

    def authenticate(self, session_token: str | None) -> Principal | None:
        if not session_token or len(session_token) > 256:
            return None
        now = self._now()
        with self.rt.db.transaction() as session:
            row = session.execute(
                select(UserSession, User)
                .join(User, User.id == UserSession.user_id)
                .where(UserSession.token_hash == hash_token(session_token))
            ).one_or_none()
            if row is None:
                return None
            record, user = row
            if (
                record.revoked_at is not None
                or record.idle_expires_at <= now
                or record.absolute_expires_at <= now
                or user.status != "active"
            ):
                return None
            if now - record.last_used_at >= self.settings.SESSION_TOUCH_INTERVAL:
                record.last_used_at = now
                record.idle_expires_at = min(
                    now + self.settings.SESSION_IDLE_TIMEOUT, record.absolute_expires_at
                )
            return Principal(
                user_id=user.id,
                session_id=record.id,
                email=user.email,
                display_name=user.display_name,
                email_verified=user.email_verified_at is not None,
            )

    def logout(self, principal: Principal, meta: RequestMeta) -> None:
        with self.rt.db.transaction(user_id=principal.user_id) as session:
            self._revoke_sessions(session, principal.user_id, "logout", only=principal.session_id)
            self._event(session, "logout", meta, principal.user_id)

    def logout_all(self, principal: Principal, meta: RequestMeta) -> None:
        with self.rt.db.transaction(user_id=principal.user_id) as session:
            self._revoke_sessions(session, principal.user_id, "logout_all")
            self._event(session, "logout_all", meta, principal.user_id)

    def list_sessions(self, principal: Principal) -> list[SessionOut]:
        now = self._now()
        with self.rt.db.transaction(user_id=principal.user_id) as session:
            rows = (
                session.execute(
                    select(UserSession)
                    .where(
                        UserSession.user_id == principal.user_id,
                        UserSession.revoked_at.is_(None),
                        UserSession.idle_expires_at > now,
                        UserSession.absolute_expires_at > now,
                    )
                    .order_by(UserSession.last_used_at.desc())
                )
                .scalars()
                .all()
            )
            return [
                SessionOut(
                    id=r.id,
                    created_at=r.created_at,
                    last_used_at=r.last_used_at,
                    auth_method=r.auth_method,
                    user_agent_summary=r.user_agent_summary,
                    current=r.id == principal.session_id,
                )
                for r in rows
            ]

    def revoke_session(
        self, principal: Principal, session_id: uuid.UUID, meta: RequestMeta
    ) -> bool:
        """Revoke one of the caller's sessions. Returns False when it is not theirs."""
        with self.rt.db.transaction(user_id=principal.user_id) as session:
            result = session.execute(
                update(UserSession)
                .where(
                    UserSession.id == session_id,
                    UserSession.user_id == principal.user_id,
                    UserSession.revoked_at.is_(None),
                )
                .values(revoked_at=self._now(), revoked_reason="user_revoked")
            )
            if result.rowcount == 0:  # type: ignore[attr-defined]
                return False
            self._event(
                session, "session_revoked", meta, principal.user_id, session_id=str(session_id)
            )
            return True

    def me(self, principal: Principal) -> UserOut:
        with self.rt.db.transaction(user_id=principal.user_id) as session:
            rows = session.execute(
                select(Membership, Organization)
                .join(Organization, Organization.id == Membership.organization_id)
                .where(
                    Membership.user_id == principal.user_id,
                    Membership.status == "active",
                    Organization.status == "active",
                )
                .order_by(Organization.name)
            ).all()
            memberships = [
                MembershipSummary(
                    organization_id=o.id,
                    organization_name=o.name,
                    organization_slug=o.slug,
                    role=m.role,
                )
                for m, o in rows
            ]
        return UserOut(
            id=principal.user_id,
            email=principal.email,
            display_name=principal.display_name,
            email_verified=principal.email_verified,
            memberships=memberships,
        )

    # ------------------------------------------------------------------ passwords
    def forgot_password(self, *, email: str, meta: RequestMeta) -> None:
        self._throttle_email_action(email, meta)
        with self.rt.db.transaction() as session:
            user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if user is None or user.status != "active":
                return
            raw = self.issue_token(
                session,
                purpose="password_reset",
                ttl=self.settings.PASSWORD_RESET_TTL,
                user_id=user.id,
                email=user.email,
            )
            self.rt.notifications.send_email(
                session,
                template="password_reset",
                recipient=user.email,
                variables={
                    "link": self._link("/reset-password", raw),
                    "expires_in": humanize(self.settings.PASSWORD_RESET_TTL),
                },
            )
            self._event(session, "password_reset_requested", meta, user.id)

    def _set_password(self, session: Session, user: User, new_password: str) -> None:
        self._check_password_policy(new_password, user.email)
        credential = session.get(UserPasswordCredential, user.id, with_for_update=True)
        now = self._now()
        if credential is None:
            session.add(
                UserPasswordCredential(
                    user_id=user.id,
                    password_hash=hash_password(new_password),
                    password_changed_at=now,
                )
            )
        else:
            credential.password_hash = hash_password(new_password)
            credential.password_changed_at = now
            credential.updated_at = now
        self.rt.notifications.send_email(
            session,
            template="password_changed",
            recipient=user.email,
            variables={"reset_link": self._link("/forgot-password")},
        )

    def reset_password(self, *, token: str, new_password: str, meta: RequestMeta) -> None:
        with self.rt.db.transaction() as session:
            record = self.consume_token(session, token, "password_reset")
            user = (
                session.get(User, record.user_id, with_for_update=True) if record.user_id else None
            )
            if user is None or user.status != "active" or user.email != record.email:
                raise InvalidToken()
            self._set_password(session, user, new_password)
            if user.email_verified_at is None:  # the reset link proves control of the address
                user.email_verified_at = self._now()
            self._revoke_sessions(session, user.id, "password_reset")
            self._event(session, "password_reset_completed", meta, user.id)

    def change_password(
        self, principal: Principal, *, current_password: str, new_password: str, meta: RequestMeta
    ) -> str:
        self.rt.throttler.hit(
            Limit(
                "login_account_ip", self.settings.THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE, MINUTE
            ),
            f"{principal.email}|{meta.ip}",
        )
        with self.rt.db.transaction(user_id=principal.user_id) as session:
            user = session.get(User, principal.user_id, with_for_update=True)
            credential = session.get(UserPasswordCredential, principal.user_id)
            if (
                user is None
                or credential is None
                or not verify_password(credential.password_hash, current_password).valid
            ):
                raise InvalidCredentials("Current password is incorrect.")
            self._set_password(session, user, new_password)
            self._revoke_sessions(session, user.id, "password_changed")
            token = self._create_session(session, user.id, meta)
            self._event(session, "password_changed", meta, user.id)
            return token
