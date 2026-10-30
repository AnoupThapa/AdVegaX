"""Authentication endpoints (API_SPECIFICATION §3)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import IdentityDep, MetaDep, PrincipalDep, RuntimeDep, SessionTokenDep
from app.api.responses import Envelope, ok
from app.core.errors import NotFound
from app.core.security.cookies import clear_session_cookie, set_csrf_cookie, set_session_cookie
from app.core.security.csrf import issue_csrf_token, session_binding
from app.domains.identity.schemas import (
    ChangePasswordRequest,
    CsrfOut,
    CsrfStatusOut,
    ForgotPasswordRequest,
    LoginOut,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionOut,
    StatusOut,
    TokenRequest,
    UserOut,
)
from app.runtime import Runtime

router = APIRouter(prefix="/auth", tags=["auth"])
ACCEPTED = StatusOut(status="accepted")


def _new_csrf(rt: Runtime, response: Response, session_token: str | None) -> str:
    token = issue_csrf_token(
        rt.settings.SECRET_KEY.get_secret_value(), session_binding(session_token)
    )
    set_csrf_cookie(response, rt.settings, token)
    return token


@router.get("/csrf", response_model=Envelope[CsrfOut])
def csrf(rt: RuntimeDep, response: Response, token: SessionTokenDep) -> Envelope[CsrfOut]:
    return ok(CsrfOut(csrf_token=_new_csrf(rt, response, token)))


@router.post("/register", status_code=status.HTTP_202_ACCEPTED, response_model=Envelope[StatusOut])
def register(body: RegisterRequest, identity: IdentityDep, meta: MetaDep) -> Envelope[StatusOut]:
    identity.register(
        email=body.email, password=body.password, display_name=body.display_name, meta=meta
    )
    return ok(ACCEPTED)


@router.post("/verify-email", response_model=Envelope[StatusOut])
def verify_email(body: TokenRequest, identity: IdentityDep, meta: MetaDep) -> Envelope[StatusOut]:
    identity.verify_email(token=body.token, meta=meta)
    return ok(StatusOut(status="verified"))


@router.post(
    "/resend-verification", status_code=status.HTTP_202_ACCEPTED, response_model=Envelope[StatusOut]
)
def resend_verification(
    principal: PrincipalDep, identity: IdentityDep, meta: MetaDep
) -> Envelope[StatusOut]:
    identity.resend_verification(principal, meta)
    return ok(ACCEPTED)


@router.post("/login", response_model=Envelope[LoginOut])
def login(
    body: LoginRequest,
    response: Response,
    rt: RuntimeDep,
    identity: IdentityDep,
    meta: MetaDep,
    current: SessionTokenDep,
) -> Envelope[LoginOut]:
    token = identity.login(
        email=body.email, password=body.password, meta=meta, previous_session_token=current
    )
    set_session_cookie(response, rt.settings, token)
    principal = identity.authenticate(token)
    if principal is None:  # pragma: no cover - a just-created session is always valid
        raise NotFound()
    return ok(LoginOut(user=identity.me(principal), csrf_token=_new_csrf(rt, response, token)))


@router.post("/logout", response_model=Envelope[CsrfStatusOut])
def logout(
    principal: PrincipalDep,
    response: Response,
    rt: RuntimeDep,
    identity: IdentityDep,
    meta: MetaDep,
) -> Envelope[CsrfStatusOut]:
    identity.logout(principal, meta)
    clear_session_cookie(response, rt.settings)
    return ok(CsrfStatusOut(status="logged_out", csrf_token=_new_csrf(rt, response, None)))


@router.post("/logout-all", response_model=Envelope[CsrfStatusOut])
def logout_all(
    principal: PrincipalDep,
    response: Response,
    rt: RuntimeDep,
    identity: IdentityDep,
    meta: MetaDep,
) -> Envelope[CsrfStatusOut]:
    identity.logout_all(principal, meta)
    clear_session_cookie(response, rt.settings)
    return ok(CsrfStatusOut(status="logged_out", csrf_token=_new_csrf(rt, response, None)))


@router.get("/me", response_model=Envelope[UserOut])
def me(principal: PrincipalDep, identity: IdentityDep) -> Envelope[UserOut]:
    return ok(identity.me(principal))


@router.get("/sessions", response_model=Envelope[list[SessionOut]])
def sessions(principal: PrincipalDep, identity: IdentityDep) -> Envelope[list[SessionOut]]:
    return ok(identity.list_sessions(principal))


@router.delete("/sessions/{session_id}", response_model=Envelope[StatusOut])
def revoke_session(
    session_id: uuid.UUID, principal: PrincipalDep, identity: IdentityDep, meta: MetaDep
) -> Envelope[StatusOut]:
    if not identity.revoke_session(principal, session_id, meta):
        raise NotFound()
    return ok(StatusOut(status="revoked"))


@router.post(
    "/forgot-password", status_code=status.HTTP_202_ACCEPTED, response_model=Envelope[StatusOut]
)
def forgot_password(
    body: ForgotPasswordRequest, identity: IdentityDep, meta: MetaDep
) -> Envelope[StatusOut]:
    identity.forgot_password(email=body.email, meta=meta)
    return ok(ACCEPTED)


@router.post("/reset-password", response_model=Envelope[CsrfStatusOut])
def reset_password(
    body: ResetPasswordRequest,
    response: Response,
    rt: RuntimeDep,
    identity: IdentityDep,
    meta: MetaDep,
) -> Envelope[CsrfStatusOut]:
    identity.reset_password(token=body.token, new_password=body.new_password, meta=meta)
    clear_session_cookie(response, rt.settings)
    return ok(CsrfStatusOut(status="password_reset", csrf_token=_new_csrf(rt, response, None)))


@router.post("/change-password", response_model=Envelope[CsrfStatusOut])
def change_password(
    body: ChangePasswordRequest,
    principal: PrincipalDep,
    response: Response,
    rt: RuntimeDep,
    identity: IdentityDep,
    meta: MetaDep,
) -> Envelope[CsrfStatusOut]:
    token = identity.change_password(
        principal, current_password=body.current_password, new_password=body.new_password, meta=meta
    )
    set_session_cookie(response, rt.settings, token)
    return ok(CsrfStatusOut(status="password_changed", csrf_token=_new_csrf(rt, response, token)))
