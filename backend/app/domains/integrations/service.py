"""Connections → discovered resources → explicit organization links (A6, A16).

Connection ownership = organization; authorization actor = user. Discovery never links
anything: a resource is used only after a Manager+ explicitly links it. Unlinking and
relinking create new link rows, so history is kept for audit.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.security.throttle import Limit
from app.core.security.tokens import generate_token
from app.domains.audit.service import Actor, record_audit
from app.domains.identity.principal import Principal
from app.domains.integrations import tokens
from app.domains.integrations.connect_state import (
    ConnectOutcome,
    ConnectState,
    consume_state,
    create_state,
    pop_outcome,
    save_outcome,
)
from app.domains.integrations.credentials import erase_secrets, load_secrets, store_secrets
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalConnectionCredential,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.integrations.schemas import (
    AuthorizationStartOut,
    ConnectionOut,
    JobOut,
    LinkOut,
    ProviderOut,
    ResourceOut,
)
from app.domains.integrations.tokens import AccountBusy, account_lock, lock_key, sign_in_ends_at
from app.domains.jobs.service import create_job
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.service import OrganizationService
from app.domains.organizations.tenancy import TenantContext
from app.providers.base.capabilities import Capability
from app.providers.base.errors import InvalidConnectParamsError, ProviderError
from app.providers.base.interfaces import PlatformProvider
from app.providers.base.pkce import pkce_challenge
from app.providers.base.types import AuthorizationRequest, ConnectResult
from app.runtime import Runtime

logger = logging.getLogger("advegax.integrations")

JOB_DISCOVER = "connection.discover"
JOB_SYNC = "resource.sync"


class ConnectionNotActive(Conflict):
    code = "CONNECTION_NOT_ACTIVE"
    message = "This connection is not active. Reconnect the platform first."


class ResourceNotLinkable(Conflict):
    code = "RESOURCE_NOT_LINKABLE"
    message = "This resource is no longer accessible through its connection."


class ResourceUnavailable(Conflict):
    """The platform says this account cannot be used (e.g. a manager or cancelled account)."""

    code = "RESOURCE_UNAVAILABLE"
    message = "This account cannot be linked."


class AlreadyLinked(Conflict):
    code = "ALREADY_LINKED"
    message = "This resource is already linked to the organization."


class AccountInUse(Conflict):
    code = "ACCOUNT_IN_USE"
    message = (
        "This account is already connected to another AdVegaX organization. "
        "Ask its owner to disconnect it first."
    )


class InvalidConnectParams(ValidationFailed):
    code = "INVALID_CONNECT_PARAMS"
    message = "Check the details you entered for this platform (for example the store address)."


class StoreNotReachable(ValidationFailed):
    code = "STORE_NOT_REACHABLE"
    message = (
        "AdVegaX could not reach the store's WooCommerce API at this address. Check the "
        "address and that the store is online."
    )


class InvalidKeyDelivery(ValidationFailed):
    code = "INVALID_KEY_DELIVERY"
    message = "The credentials could not be accepted."


class InstallNotSupported(NotFound):
    code = "UNKNOWN_PROVIDER"
    message = "This platform is not available."


ACCOUNT_IN_USE_CODE = "account_in_use"
MAX_PARAM_LENGTH = 255


class NotLinked(Conflict):
    code = "NOT_LINKED"
    message = "This resource is not linked to the organization."


def _connection_out(
    c: ExternalConnection, sign_in_expires_at: datetime | None = None
) -> ConnectionOut:
    return ConnectionOut(
        id=c.id,
        provider=c.provider,
        auth_scheme=c.auth_scheme,
        status=c.status,
        authorized_by_user_id=c.authorized_by_user_id,
        granted_scopes=list(c.granted_scopes),
        account_label=c.external_account_label,
        last_error_code=c.last_error_code,
        created_at=c.created_at,
        revoked_at=c.revoked_at,
        sign_in_expires_at=sign_in_expires_at if c.status != "revoked" else None,
    )


def _link_out(link: OrganizationResourceLink) -> LinkOut:
    return LinkOut(
        id=link.id,
        resource_id=link.external_resource_id,
        status=link.status,
        linked_at=link.linked_at,
        unlinked_at=link.unlinked_at,
        unlink_reason=link.unlink_reason,
    )


def _job_out(job_id: uuid.UUID, job_type: str) -> JobOut:
    return JobOut(
        id=job_id,
        job_type=job_type,
        status="queued",
        attempts=0,
        max_attempts=0,
        last_error_code=None,
    )


class IntegrationService:
    def __init__(self, runtime: Runtime, organizations: OrganizationService) -> None:
        self.rt = runtime
        self.organizations = organizations

    def _redirect_uri(self, provider: str) -> str:
        return f"{self.rt.settings.API_BASE_URL.rstrip('/')}/api/v1/connections/{provider}/callback"

    def _delivery_uri(self, provider: str) -> str:
        base = self.rt.settings.API_BASE_URL.rstrip("/")
        return f"{base}/api/v1/connections/{provider}/credentials"

    def list_providers(self) -> list[ProviderOut]:
        """Platforms available in this environment (empty in staging/production until 2A)."""
        return [
            ProviderOut(
                code=p.code,
                display_name=p.display_name,
                category=p.category.value,
                auth_scheme=p.auth_scheme.value,
                capabilities=p.capabilities.as_dict(),
                test_only=p.test_only,
            )
            for p in self.rt.providers.all()
        ]

    def _app_redirect(self, **params: str) -> str:
        return f"{self.rt.settings.APP_BASE_URL.rstrip('/')}/connections?{urlencode(params)}"

    # ----------------------------------------------------------- authorization flow
    def _live_account_owner(self, provider: str, account_id: str) -> uuid.UUID | None:
        """Organization holding a live connection to this platform account, if any (Q6).

        A narrow system-role lookup: the app role cannot see other tenants' connections. It
        answers only "connected elsewhere: yes/no" and never returns another tenant's data.
        """
        with self.rt.db.transaction(system=True) as session:
            return session.execute(
                select(ExternalConnection.organization_id)
                .where(
                    ExternalConnection.provider == provider,
                    ExternalConnection.external_account_id == account_id,
                    ExternalConnection.status != "revoked",
                )
                .limit(1)
            ).scalar_one_or_none()

    def start(
        self, ctx: TenantContext, provider_code: str, params: dict[str, str] | None = None
    ) -> AuthorizationStartOut:
        authorize(ctx, Permission.CONNECTIONS_MANAGE)
        provider = self.rt.providers.get(provider_code)
        raw = params or {}
        if any(len(k) > 64 or len(v) > MAX_PARAM_LENGTH for k, v in raw.items()):
            raise InvalidConnectParams()
        try:
            prepared = provider.prepare_connect(raw)
        except InvalidConnectParamsError:
            raise InvalidConnectParams() from None
        if prepared.account_id is not None:
            owner = self._live_account_owner(provider.code, prepared.account_id)
            if owner is not None and owner != ctx.organization_id:
                raise AccountInUse()
        verifier = generate_token() if provider.capabilities.supports(Capability.PKCE) else None
        ttl = self.rt.settings.CONNECT_STATE_TTL
        state = create_state(
            self.rt.redis,
            ConnectState(
                ctx.organization_id, ctx.user_id, provider.code, verifier, dict(prepared.params)
            ),
            ttl,
        )
        delivers = provider.capabilities.supports(Capability.KEY_DELIVERY)
        try:
            url = provider.authorization_url(
                AuthorizationRequest(
                    state=state,
                    redirect_uri=self._redirect_uri(provider.code),
                    code_challenge=pkce_challenge(verifier) if verifier else None,
                    provider_params=dict(prepared.params),
                    delivery_uri=self._delivery_uri(provider.code) if delivers else None,
                )
            )
        except ProviderError as exc:  # e.g. a self-hosted store that cannot be reached
            consume_state(self.rt.redis, state)
            raise StoreNotReachable(details=[{"reason": exc.code}]) from None
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="connection.authorization_started",
                resource_type="connection",
                resource_id=None,
                metadata={"provider": provider.code},
            )
        return AuthorizationStartOut(authorize_url=url, expires_in_seconds=int(ttl.total_seconds()))

    def complete(
        self, principal: Principal | None, provider_code: str, params: dict[str, str]
    ) -> str:
        """Handle the provider callback; always returns a redirect URL into the web app."""
        try:
            delivering = self.rt.providers.get(provider_code)
        except NotFound:
            delivering = None
        if delivering is not None and delivering.capabilities.supports(Capability.KEY_DELIVERY):
            return self._return_from_delivery(principal, params)
        state = consume_state(self.rt.redis, params.get("state"))
        if state is None or state.provider != provider_code:
            return self._app_redirect(status="error", code="invalid_state")
        if principal is None or principal.user_id != state.user_id:
            return self._app_redirect(status="error", code="session_mismatch")
        try:
            ctx = self.organizations.resolve_tenant(principal, state.organization_id)
            authorize(ctx, Permission.CONNECTIONS_MANAGE)
        except (NotFound, Forbidden):  # membership or role changed since the flow started
            return self._app_redirect(status="error", code="not_permitted")
        # From here the signed-in user is confirmed as a manager of this organization, so the
        # web app may be told which organization to open (PHASE_01C_PLAN §6).
        org_param = str(ctx.organization_id)
        if "error" in params:
            return self._app_redirect(status="cancelled", organization_id=org_param)
        provider = self.rt.providers.get(provider_code)
        try:
            prepared = provider.prepare_connect(state.provider_params)
        except InvalidConnectParamsError:
            return self._app_redirect(
                status="error", code="invalid_connect_params", organization_id=org_param
            )
        # Exchanging the code would retire another organization's token for this account on
        # platforms like Shopify, so the one-live-connection rule is checked BEFORE it (Q6).
        if prepared.account_id is not None:
            owner = self._live_account_owner(provider.code, prepared.account_id)
            if owner is not None and owner != ctx.organization_id:
                return self._app_redirect(
                    status="error", code=ACCOUNT_IN_USE_CODE, organization_id=org_param
                )
        # A reconnect must never overlap a token refresh of the same account: acquiring a new
        # token retires the other one (2A-04). Accounts without an id get a no-op scope.
        lock = (
            account_lock(
                self.rt.redis,
                lock_key(provider.code, prepared.account_id, ctx.organization_id),
                wait_seconds=tokens.LOCK_WAIT_SECONDS,
            )
            if prepared.account_id is not None
            else nullcontext()
        )
        try:
            with lock:
                try:
                    result = provider.complete_authorization(
                        params,
                        redirect_uri=self._redirect_uri(provider.code),
                        code_verifier=state.code_verifier,
                        provider_params=prepared.params,
                    )
                except ProviderError as exc:
                    logger.warning(
                        "connect_failed", extra={"provider": provider.code, "error_code": exc.code}
                    )
                    return self._app_redirect(
                        status="error", code=exc.code, organization_id=org_param
                    )
                try:
                    connection_id = self._save_connection(ctx, provider, result)
                except IntegrityError:  # another organization connected this account meanwhile
                    return self._app_redirect(
                        status="error", code=ACCOUNT_IN_USE_CODE, organization_id=org_param
                    )
        except AccountBusy as exc:
            return self._app_redirect(status="error", code=exc.code, organization_id=org_param)
        return self._app_redirect(
            status="connected", organization_id=org_param, connection_id=str(connection_id)
        )

    # ----------------------------------------------------------- delivered credentials (2B-04)
    def deliver_credentials(self, provider_code: str, body: bytes, *, ip: str) -> None:
        """A platform posts the credentials it generated (e.g. WooCommerce), server to server.

        Authenticated only by the single-use connect state it echoes back (``user_id``), which
        is consumed at once. The credentials are verified **against the store recorded in that
        state** — the posted body never chooses what AdVegaX calls — and only then stored.
        The outcome is kept briefly for the browser's return. Raises ``InvalidKeyDelivery``
        (400, nothing echoed) on any failure, so the platform shows the merchant an error.
        """
        self.rt.throttler.hit(
            Limit(
                "key_delivery_ip", self.rt.settings.THROTTLE_KEY_DELIVERY_PER_IP_PER_MINUTE, MINUTE
            ),
            ip,
        )
        try:
            provider = self.rt.providers.get(provider_code)
        except NotFound:
            raise InvalidKeyDelivery() from None
        if not provider.capabilities.supports(Capability.KEY_DELIVERY):
            raise InvalidKeyDelivery()
        fields = _delivered_fields(body)
        if fields is None:
            raise InvalidKeyDelivery()
        token = fields.get("user_id")
        state = consume_state(self.rt.redis, token)
        if state is None or state.provider != provider.code or token is None:
            raise InvalidKeyDelivery()
        outcome = self._accept_delivery(provider, state, fields)
        save_outcome(self.rt.redis, token, outcome, self.rt.settings.CONNECT_STATE_TTL)
        if outcome.status != "connected":
            logger.warning(
                "key_delivery_refused",
                extra={"provider": provider.code, "error_code": outcome.code},
            )
            raise InvalidKeyDelivery()

    def _accept_delivery(
        self, provider: PlatformProvider, state: ConnectState, fields: dict[str, str]
    ) -> ConnectOutcome:
        def failed(code: str) -> ConnectOutcome:
            return ConnectOutcome(state.user_id, state.organization_id, "error", code=code)

        try:
            ctx = self.organizations.tenant_for_user(state.user_id, state.organization_id)
            authorize(ctx, Permission.CONNECTIONS_MANAGE)
        except (NotFound, Forbidden):  # membership or role changed since the flow started
            return failed("not_permitted")
        try:
            prepared = provider.prepare_connect(state.provider_params)
        except InvalidConnectParamsError:
            return failed("invalid_connect_params")
        if prepared.account_id is not None:
            owner = self._live_account_owner(provider.code, prepared.account_id)
            if owner is not None and owner != ctx.organization_id:
                return failed(ACCOUNT_IN_USE_CODE)
        lock = (
            account_lock(
                self.rt.redis,
                lock_key(provider.code, prepared.account_id, ctx.organization_id),
                wait_seconds=tokens.LOCK_WAIT_SECONDS,
            )
            if prepared.account_id is not None
            else nullcontext()
        )
        try:
            with lock:
                try:
                    result = provider.complete_authorization(
                        fields,
                        redirect_uri=self._redirect_uri(provider.code),
                        code_verifier=None,
                        provider_params=prepared.params,
                    )
                except ProviderError as exc:
                    return failed(exc.code)
                if (
                    prepared.account_id is not None
                    and result.external_account_id != prepared.account_id
                ):
                    return failed("account_mismatch")
                try:
                    connection_id = self._save_connection(ctx, provider, result)
                except IntegrityError:
                    return failed(ACCOUNT_IN_USE_CODE)
        except AccountBusy as exc:
            return failed(exc.code)
        return ConnectOutcome(
            state.user_id, state.organization_id, "connected", connection_id=connection_id
        )

    def _return_from_delivery(self, principal: Principal | None, params: dict[str, str]) -> str:
        """The browser's way back after the platform delivered (or did not deliver) the
        credentials. Shows the stored outcome to the same signed-in person, once."""
        token = params.get("user_id")
        outcome = pop_outcome(self.rt.redis, token)
        if outcome is None:
            state = consume_state(self.rt.redis, token)  # never delivered: retire the state
            if state is None:
                return self._app_redirect(status="error", code="invalid_state")
            if principal is None or principal.user_id != state.user_id:
                return self._app_redirect(status="error", code="session_mismatch")
            org = str(state.organization_id)
            if params.get("success") == "0":
                return self._app_redirect(status="cancelled", organization_id=org)
            return self._app_redirect(status="error", code="key_not_delivered", organization_id=org)
        if principal is None or principal.user_id != outcome.user_id:
            return self._app_redirect(status="error", code="session_mismatch")
        org = str(outcome.organization_id)
        if outcome.status == "connected" and outcome.connection_id is not None:
            return self._app_redirect(
                status="connected", organization_id=org, connection_id=str(outcome.connection_id)
            )
        return self._app_redirect(
            status="error", code=outcome.code or "connect_failed", organization_id=org
        )

    def _save_connection(
        self, ctx: TenantContext, provider: PlatformProvider, result: ConnectResult
    ) -> uuid.UUID:
        """Create the connection — or, when this organization reconnects the same platform
        account, reuse its existing connection so stores and imported data are kept (§6.4a)."""
        now = self.rt.clock.now()
        account_id = result.external_account_id
        if account_id is not None and result.account_per_organization:
            # Unique per organization only: the live-account rule (Q6) does not apply.
            account_id = f"{ctx.organization_id}:{account_id}"
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            existing = None
            if account_id is not None:
                existing = (
                    session.execute(
                        select(ExternalConnection)
                        .where(
                            ExternalConnection.organization_id == ctx.organization_id,
                            ExternalConnection.provider == provider.code,
                            ExternalConnection.external_account_id == account_id,
                        )
                        .order_by(ExternalConnection.created_at.desc())
                        .limit(1)
                        .with_for_update()
                    )
                    .scalars()
                    .first()
                )
            if existing is not None:
                connection = existing
                before = {"status": connection.status}
                connection.status = "active"
                connection.authorized_by_user_id = ctx.user_id
                connection.granted_scopes = list(result.granted_scopes)
                connection.external_account_label = result.account_label
                connection.last_error_code = connection.last_error_at = None
                connection.revoked_at = None
                connection.updated_at = now
                action = "connection.reconnected"
            else:
                connection = ExternalConnection(
                    organization_id=ctx.organization_id,
                    provider=provider.code,
                    auth_scheme=provider.auth_scheme.value,
                    authorized_by_user_id=ctx.user_id,
                    granted_scopes=list(result.granted_scopes),
                    external_account_label=result.account_label,
                    external_account_id=account_id,
                )
                session.add(connection)
                before = None
                action = "connection.created"
            session.flush()  # the live-account unique index is enforced here
            expires = (
                now + timedelta(seconds=result.token_expires_in_seconds)
                if result.token_expires_in_seconds
                else None
            )
            refresh_expires = (
                now + timedelta(seconds=result.refresh_expires_in_seconds)
                if result.refresh_expires_in_seconds
                else None
            )
            store_secrets(
                session,
                self.rt.cipher,
                connection,
                result.secrets,
                token_expires_at=expires,
                refresh_expires_at=refresh_expires,
            )
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action=action,
                resource_type="connection",
                resource_id=connection.id,
                before=before,
                after={"provider": provider.code, "scopes": list(result.granted_scopes)},
            )
            create_job(
                session,
                self.rt,
                organization_id=ctx.organization_id,
                job_type=JOB_DISCOVER,
                subject_type="connection",
                subject_id=connection.id,
                requested_by=ctx.user_id,
            )
            return connection.id

    def install(self, provider_code: str, params: dict[str, str]) -> str:
        """A platform-initiated install (e.g. a Shopify install link). Nothing is stored here:
        the person is sent to the web app to sign in and choose the organization, which then
        starts the normal, state-protected authorization (D-2A-1)."""
        try:
            provider = self.rt.providers.get(provider_code)
        except NotFound:
            return self._app_redirect(status="error", code="unknown_provider")
        if not provider.capabilities.supports(Capability.APP_INSTALL):
            return self._app_redirect(status="error", code="unsupported")
        try:
            account = provider.verify_install(params)
        except ProviderError as exc:
            logger.warning(
                "install_refused", extra={"provider": provider.code, "error_code": exc.code}
            )
            return self._app_redirect(status="error", code=exc.code)
        base = self.rt.settings.APP_BASE_URL.rstrip("/")
        return f"{base}/connect/{provider.code}?{urlencode({'account': account})}"

    def revoke_by_platform(self, provider_code: str, account_id: str, *, reason: str) -> int:
        """See ``revoke_by_platform`` (module function, also used by webhook processing)."""
        return revoke_by_platform(self.rt, provider_code, account_id, reason=reason)

    # ----------------------------------------------------------- connections
    def _get_connection(
        self, session: Session, ctx: TenantContext, connection_id: uuid.UUID, *, lock: bool = False
    ) -> ExternalConnection:
        stmt = select(ExternalConnection).where(
            ExternalConnection.id == connection_id,
            ExternalConnection.organization_id == ctx.organization_id,
        )
        connection = session.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()
        if connection is None:
            raise NotFound()
        return connection

    def list_connections(self, ctx: TenantContext) -> list[ConnectionOut]:
        authorize(ctx, Permission.CONNECTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            rows = session.execute(
                select(ExternalConnection, ExternalConnectionCredential.token_expires_at)
                .outerjoin(
                    ExternalConnectionCredential,
                    ExternalConnectionCredential.connection_id == ExternalConnection.id,
                )
                .where(ExternalConnection.organization_id == ctx.organization_id)
                .order_by(ExternalConnection.created_at.desc())
            ).all()
            return [
                _connection_out(c, sign_in_ends_at(self.rt, c.provider, expires))
                for c, expires in rows
            ]

    def get_connection(self, ctx: TenantContext, connection_id: uuid.UUID) -> ConnectionOut:
        authorize(ctx, Permission.CONNECTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            connection = self._get_connection(session, ctx, connection_id)
            record = session.get(ExternalConnectionCredential, connection.id)
            expires = record.token_expires_at if record is not None else None
            return _connection_out(
                connection, sign_in_ends_at(self.rt, connection.provider, expires)
            )

    def disconnect(self, ctx: TenantContext, connection_id: uuid.UUID) -> ConnectionOut:
        authorize(ctx, Permission.CONNECTIONS_MANAGE)
        now = self.rt.clock.now()
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            connection = self._get_connection(session, ctx, connection_id, lock=True)
            if connection.status == "revoked":
                return _connection_out(connection)
            provider = self.rt.providers.get(connection.provider)
            revoked_at_provider = False
            try:
                provider.revoke(load_secrets(session, self.rt.cipher, connection))
                revoked_at_provider = True
            except ProviderError as exc:
                logger.warning(
                    "provider_revoke_failed",
                    extra={"provider": connection.provider, "error_code": exc.code},
                )
            erase_secrets(session, connection.id)
            ended = self._end_links(
                session,
                ctx.organization_id,
                ExternalResource.connection_id == connection.id,
                reason="connection_revoked",
                by=ctx.user_id,
                now=now,
            )
            before = {"status": connection.status}
            connection.status, connection.revoked_at, connection.updated_at = "revoked", now, now
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="connection.revoked",
                resource_type="connection",
                resource_id=connection.id,
                before=before,
                after={"status": "revoked"},
                metadata={"revoked_at_provider": revoked_at_provider, "links_ended": ended},
            )
            return _connection_out(connection)

    def _end_links(
        self,
        session: Session,
        org_id: uuid.UUID,
        condition: ColumnElement[bool],
        *,
        reason: str,
        by: uuid.UUID | None,
        now: datetime,
    ) -> int:
        return end_links(session, org_id, condition, reason=reason, by=by, now=now)

    def rediscover(self, ctx: TenantContext, connection_id: uuid.UUID) -> JobOut:
        authorize(ctx, Permission.CONNECTIONS_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            connection = self._get_connection(session, ctx, connection_id)
            if connection.status != "active":
                raise ConnectionNotActive()
            job = create_job(
                session,
                self.rt,
                organization_id=ctx.organization_id,
                job_type=JOB_DISCOVER,
                subject_type="connection",
                subject_id=connection.id,
                requested_by=ctx.user_id,
            )
            return _job_out(job.id, JOB_DISCOVER)

    # ----------------------------------------------------------- resources & links
    def list_resources(self, ctx: TenantContext, connection_id: uuid.UUID) -> list[ResourceOut]:
        authorize(ctx, Permission.CONNECTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            self._get_connection(session, ctx, connection_id)
            rows = session.execute(
                select(ExternalResource, OrganizationResourceLink.id)
                .outerjoin(
                    OrganizationResourceLink,
                    (OrganizationResourceLink.external_resource_id == ExternalResource.id)
                    & (OrganizationResourceLink.status == "active"),
                )
                .where(
                    ExternalResource.connection_id == connection_id,
                    ExternalResource.organization_id == ctx.organization_id,
                )
                .order_by(ExternalResource.kind, ExternalResource.external_id)
            ).all()
            return [
                ResourceOut(
                    id=r.id,
                    connection_id=r.connection_id,
                    provider=r.provider,
                    kind=r.kind,
                    external_id=r.external_id,
                    display_name=r.display_name,
                    currency=r.currency,
                    timezone=r.timezone,
                    accessible=r.accessible,
                    unavailable_reason=r.unavailable_reason,
                    group_path=r.group_path,
                    capabilities=r.capabilities,
                    linked=link_id is not None,
                    link_id=link_id,
                    discovered_at=r.discovered_at,
                    last_synced_at=r.last_synced_at,
                )
                for r, link_id in rows
            ]

    def _get_resource(
        self, session: Session, ctx: TenantContext, resource_id: uuid.UUID
    ) -> tuple[ExternalResource, ExternalConnection]:
        row = session.execute(
            select(ExternalResource, ExternalConnection)
            .join(ExternalConnection, ExternalConnection.id == ExternalResource.connection_id)
            .where(
                ExternalResource.id == resource_id,
                ExternalResource.organization_id == ctx.organization_id,
            )
            .with_for_update(of=ExternalResource)
        ).one_or_none()
        if row is None:
            raise NotFound()
        return row[0], row[1]

    def _active_link(
        self, session: Session, resource_id: uuid.UUID
    ) -> OrganizationResourceLink | None:
        return session.execute(
            select(OrganizationResourceLink)
            .where(
                OrganizationResourceLink.external_resource_id == resource_id,
                OrganizationResourceLink.status == "active",
            )
            .with_for_update()
        ).scalar_one_or_none()

    def link(self, ctx: TenantContext, resource_id: uuid.UUID) -> LinkOut:
        authorize(ctx, Permission.CONNECTIONS_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            resource, connection = self._get_resource(session, ctx, resource_id)
            if connection.status != "active":
                raise ConnectionNotActive()
            if not resource.accessible:
                raise ResourceNotLinkable()
            if resource.unavailable_reason is not None:  # e.g. a cancelled ad account (Q-3-3)
                raise ResourceUnavailable(details=[{"reason": resource.unavailable_reason}])
            if self._active_link(session, resource.id) is not None:
                raise AlreadyLinked()
            link = OrganizationResourceLink(
                organization_id=ctx.organization_id,
                external_resource_id=resource.id,
                linked_by_user_id=ctx.user_id,
                linked_at=self.rt.clock.now(),
            )
            session.add(link)
            session.flush()
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="resource.linked",
                resource_type="external_resource",
                resource_id=resource.id,
                after={
                    "link_id": link.id,
                    "kind": resource.kind,
                    "external_id": resource.external_id,
                },
            )
            # Commerce stores: create the store and start its initial import (2A-06).
            from app.domains.commerce.importer import on_store_linked

            on_store_linked(
                session, self.rt, resource=resource, connection=connection, user_id=ctx.user_id
            )
            # Ad accounts: create the account and start its import (3-05).
            from app.domains.advertising.importer import on_ad_account_linked

            on_ad_account_linked(
                session, self.rt, resource=resource, connection=connection, user_id=ctx.user_id
            )
            # Analytics properties: create the property and start its import (5-05).
            from app.domains.analytics.importer import on_property_linked

            on_property_linked(
                session, self.rt, resource=resource, connection=connection, user_id=ctx.user_id
            )
            return _link_out(link)

    def unlink(self, ctx: TenantContext, resource_id: uuid.UUID) -> LinkOut:
        authorize(ctx, Permission.CONNECTIONS_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            resource, _ = self._get_resource(session, ctx, resource_id)
            link = self._active_link(session, resource.id)
            if link is None:
                raise NotLinked()
            link.status, link.unlinked_at, link.unlinked_by_user_id, link.unlink_reason = (
                "unlinked",
                self.rt.clock.now(),
                ctx.user_id,
                "user",
            )
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="resource.unlinked",
                resource_type="external_resource",
                resource_id=resource.id,
                before={"link_id": link.id, "status": "active"},
                after={"status": "unlinked"},
            )
            return _link_out(link)

    def link_history(self, ctx: TenantContext, resource_id: uuid.UUID) -> list[LinkOut]:
        authorize(ctx, Permission.CONNECTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            self._get_resource(session, ctx, resource_id)
            links = (
                session.execute(
                    select(OrganizationResourceLink)
                    .where(OrganizationResourceLink.external_resource_id == resource_id)
                    # Equal link times (same moment): ended links before the current one.
                    .order_by(
                        OrganizationResourceLink.linked_at,
                        OrganizationResourceLink.unlinked_at.asc().nulls_last(),
                    )
                )
                .scalars()
                .all()
            )
            return [_link_out(link) for link in links]

    def request_sync(self, ctx: TenantContext, resource_id: uuid.UUID) -> JobOut:
        authorize(ctx, Permission.CONNECTIONS_MANAGE)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            resource, connection = self._get_resource(session, ctx, resource_id)
            if connection.status != "active":
                raise ConnectionNotActive()
            if self._active_link(session, resource.id) is None:
                raise NotLinked()
            job = create_job(
                session,
                self.rt,
                organization_id=ctx.organization_id,
                job_type=JOB_SYNC,
                subject_type="external_resource",
                subject_id=resource.id,
                requested_by=ctx.user_id,
            )
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="resource.sync_requested",
                resource_type="external_resource",
                resource_id=resource.id,
                metadata={"job_id": job.id},
            )
            return _job_out(job.id, JOB_SYNC)


def end_links(
    session: Session,
    org_id: uuid.UUID,
    condition: ColumnElement[bool],
    *,
    reason: str,
    by: uuid.UUID | None,
    now: datetime,
) -> int:
    links = (
        session.execute(
            select(OrganizationResourceLink)
            .join(
                ExternalResource,
                ExternalResource.id == OrganizationResourceLink.external_resource_id,
            )
            .where(
                OrganizationResourceLink.organization_id == org_id,
                OrganizationResourceLink.status == "active",
                condition,
            )
            .with_for_update(of=OrganizationResourceLink)
        )
        .scalars()
        .all()
    )
    for link in links:
        link.status, link.unlinked_at, link.unlinked_by_user_id, link.unlink_reason = (
            "unlinked",
            now,
            by,
            reason,
        )
    return len(links)


def revoke_by_platform(
    rt: Runtime,
    provider_code: str,
    account_id: str,
    *,
    reason: str,
    organization_id: uuid.UUID | None = None,
) -> int:
    """The platform says AdVegaX's access ended (e.g. Shopify ``app/uninstalled``).

    Marks every live connection to that account as revoked (limited to ``organization_id``
    when given), deletes its stored tokens and ends its links; imported data is kept until the
    platform asks for erasure (D-2A-2). Returns the number of connections changed.
    """
    with rt.db.transaction(system=True) as session:
        stmt = select(ExternalConnection.id, ExternalConnection.organization_id).where(
            ExternalConnection.provider == provider_code,
            ExternalConnection.external_account_id == account_id,
            ExternalConnection.status != "revoked",
        )
        if organization_id is not None:
            stmt = stmt.where(ExternalConnection.organization_id == organization_id)
        targets = session.execute(stmt).all()
    now = rt.clock.now()
    changed = 0
    for connection_id, org_id in targets:
        with rt.db.transaction(org_id=org_id) as session:
            connection = session.get(ExternalConnection, connection_id, with_for_update=True)
            if connection is None or connection.status == "revoked":
                continue
            erase_secrets(session, connection.id)
            ended = end_links(
                session,
                org_id,
                ExternalResource.connection_id == connection.id,
                reason="connection_revoked",
                by=None,
                now=now,
            )
            before = {"status": connection.status}
            connection.status, connection.revoked_at, connection.updated_at = "revoked", now, now
            connection.last_error_code = reason
            record_audit(
                session,
                organization_id=org_id,
                actor=Actor("system", None),
                action="connection.revoked_by_platform",
                resource_type="connection",
                resource_id=connection.id,
                before=before,
                after={"status": "revoked"},
                metadata={"reason": reason, "links_ended": ended},
            )
            changed += 1
    return changed


MAX_DELIVERY_FIELD = 512
MINUTE = 60


def _delivered_fields(body: bytes) -> dict[str, str] | None:
    """The posted credentials as plain strings, or ``None`` when the body is not a small,
    flat JSON object (nothing from it is ever logged or echoed)."""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or len(data) > 20:
        return None
    fields: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or len(key) > 64:
            return None
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        text = str(value)
        if len(text) > MAX_DELIVERY_FIELD:
            return None
        fields[key] = text
    return fields
