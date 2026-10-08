"""Connections → discovered resources → explicit organization links (A6, A16).

Connection ownership = organization; authorization actor = user. Discovery never links
anything: a resource is used only after a Manager+ explicitly links it. Unlinking and
relinking create new link rows, so history is kept for audit.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound
from app.core.security.tokens import generate_token
from app.domains.audit.service import Actor, record_audit
from app.domains.identity.principal import Principal
from app.domains.integrations.connect_state import ConnectState, consume_state, create_state
from app.domains.integrations.credentials import erase_secrets, load_secrets, store_secrets
from app.domains.integrations.models import (
    ExternalConnection,
    ExternalResource,
    OrganizationResourceLink,
)
from app.domains.integrations.schemas import (
    AuthorizationStartOut,
    ConnectionOut,
    JobOut,
    LinkOut,
    ResourceOut,
)
from app.domains.jobs.service import create_job
from app.domains.organizations.permissions import Permission, authorize
from app.domains.organizations.service import OrganizationService
from app.domains.organizations.tenancy import TenantContext
from app.providers.base.capabilities import Capability
from app.providers.base.errors import ProviderError
from app.providers.base.pkce import pkce_challenge
from app.providers.base.types import AuthorizationRequest
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


class AlreadyLinked(Conflict):
    code = "ALREADY_LINKED"
    message = "This resource is already linked to the organization."


class NotLinked(Conflict):
    code = "NOT_LINKED"
    message = "This resource is not linked to the organization."


def _connection_out(c: ExternalConnection) -> ConnectionOut:
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

    def _app_redirect(self, **params: str) -> str:
        return f"{self.rt.settings.APP_BASE_URL.rstrip('/')}/connections?{urlencode(params)}"

    # ----------------------------------------------------------- authorization flow
    def start(self, ctx: TenantContext, provider_code: str) -> AuthorizationStartOut:
        authorize(ctx, Permission.CONNECTIONS_MANAGE)
        provider = self.rt.providers.get(provider_code)
        verifier = generate_token() if provider.capabilities.supports(Capability.PKCE) else None
        ttl = self.rt.settings.CONNECT_STATE_TTL
        state = create_state(
            self.rt.redis,
            ConnectState(ctx.organization_id, ctx.user_id, provider.code, verifier),
            ttl,
        )
        url = provider.authorization_url(
            AuthorizationRequest(
                state=state,
                redirect_uri=self._redirect_uri(provider.code),
                code_challenge=pkce_challenge(verifier) if verifier else None,
            )
        )
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
        if "error" in params:
            return self._app_redirect(status="cancelled")
        provider = self.rt.providers.get(provider_code)
        try:
            result = provider.complete_authorization(
                params,
                redirect_uri=self._redirect_uri(provider.code),
                code_verifier=state.code_verifier,
            )
        except ProviderError as exc:
            logger.warning(
                "connect_failed", extra={"provider": provider.code, "error_code": exc.code}
            )
            return self._app_redirect(status="error", code=exc.code)
        now = self.rt.clock.now()
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            connection = ExternalConnection(
                organization_id=ctx.organization_id,
                provider=provider.code,
                auth_scheme=provider.auth_scheme.value,
                authorized_by_user_id=ctx.user_id,
                granted_scopes=list(result.granted_scopes),
                external_account_label=result.account_label,
            )
            session.add(connection)
            session.flush()
            expires = (
                now + timedelta(seconds=result.token_expires_in_seconds)
                if result.token_expires_in_seconds
                else None
            )
            store_secrets(
                session, self.rt.cipher, connection, result.secrets, token_expires_at=expires
            )
            record_audit(
                session,
                organization_id=ctx.organization_id,
                actor=Actor.user(ctx.user_id),
                action="connection.created",
                resource_type="connection",
                resource_id=connection.id,
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
            connection_id = connection.id
        return self._app_redirect(status="connected", connection_id=str(connection_id))

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
            rows = (
                session.execute(
                    select(ExternalConnection)
                    .where(ExternalConnection.organization_id == ctx.organization_id)
                    .order_by(ExternalConnection.created_at.desc())
                )
                .scalars()
                .all()
            )
            return [_connection_out(c) for c in rows]

    def get_connection(self, ctx: TenantContext, connection_id: uuid.UUID) -> ConnectionOut:
        authorize(ctx, Permission.CONNECTIONS_VIEW)
        with self.rt.db.transaction(org_id=ctx.organization_id, user_id=ctx.user_id) as session:
            return _connection_out(self._get_connection(session, ctx, connection_id))

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
                    .order_by(OrganizationResourceLink.linked_at)
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
