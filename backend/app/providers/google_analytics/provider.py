"""Google Analytics 4 provider (Phase 5; PHASE_05_PLAN §6): sign-in and token lifecycle (5-03),
property discovery (5-04) and daily reports in three views (5-05).

Read-only. The Google sign-in is shared with Google Ads (``providers/google``): the same
Google Cloud OAuth client, PKCE and offline access. This connection asks only for
``analytics.readonly`` and ``openid`` (Q-5-2) — never the edit permission. Each product is its
own connection, so either can be removed alone.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import date
from typing import Any

from app.core.clock import Clock
from app.providers.base.capabilities import Capability, ProviderCapabilities
from app.providers.base.errors import InvalidConnectParamsError, UnsupportedOperationError
from app.providers.base.interfaces import Secrets
from app.providers.base.types import (
    AnalyticsBreakdown,
    AnalyticsDailyRecord,
    AnalyticsPropertyRef,
    AnalyticsPropertyState,
    AnalyticsQuality,
    AuthorizationRequest,
    AuthScheme,
    ConnectResult,
    PreparedConnect,
    ProviderCategory,
    ResourceDescriptor,
    SyncSummary,
    WebhookDelivery,
)
from app.providers.google.oauth import (
    GoogleOAuth,
    HttpFactory,
    SignInRejectedError,
    UnexpectedResponseError,
)
from app.providers.google_analytics import mapping
from app.providers.google_analytics.client import (
    GoogleAnalyticsClient,
    NoPropertyAccessError,
    valid_property_id,
)

logger = logging.getLogger("advegax.providers.google_analytics")

ANALYTICS_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
MAX_PROPERTIES = 500  # one properties.get each; more than any one business has
MAX_REPORT_PAGES = 25  # 250,000 rows of one view in one slice; the rest is marked truncated


class GoogleAnalyticsProvider:
    code = "google_analytics"
    display_name = "Google Analytics"
    category = ProviderCategory.ANALYTICS
    auth_scheme = AuthScheme.OAUTH2
    capabilities = ProviderCapabilities(
        frozenset({Capability.PKCE, Capability.TOKEN_REFRESH, Capability.TOKEN_REVOCATION})
    )
    test_only = False
    rate_limit = (5.0, 10)  # per connection; Google's property quota paces the rest (5-06)

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        api_version: str,
        http_factory: HttpFactory,
        clock: Clock,
    ) -> None:
        self._clock = clock
        self._oauth = GoogleOAuth(
            client_id=client_id,
            client_secret=client_secret,
            http_factory=http_factory,
            clock=clock,
            product_scope=ANALYTICS_SCOPE,
            label="Google Analytics",
        )
        self.analytics = GoogleAnalyticsClient(http_factory, api_version)

    # ------------------------------------------------------------------ connect
    def prepare_connect(self, params: Mapping[str, str]) -> PreparedConnect:
        if params:  # nothing to type: the person chooses their Google account at Google
            raise InvalidConnectParamsError()
        return PreparedConnect()

    def authorization_url(self, request: AuthorizationRequest) -> str:
        return self._oauth.authorization_url(request)

    def complete_authorization(
        self,
        params: Mapping[str, str],
        *,
        redirect_uri: str,
        code_verifier: str | None,
        provider_params: Mapping[str, str],  # noqa: ARG002 - nothing is typed for Google
    ) -> ConnectResult:
        return self._oauth.complete(params, redirect_uri=redirect_uri, code_verifier=code_verifier)

    def verify_install(self, params: Mapping[str, str]) -> str:  # noqa: ARG002
        raise UnsupportedOperationError()

    # ------------------------------------------------------------------ token lifecycle
    def refresh_credentials(self, secrets: Secrets) -> ConnectResult:
        return self._oauth.refresh(secrets)

    def revoke(self, secrets: Secrets) -> None:
        """Disconnect: revoking the refresh token at Google also ends its access tokens."""
        self._oauth.revoke(secrets)

    # ------------------------------------------------------------------ not used by GA4
    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookDelivery:  # noqa: ARG002
        raise UnsupportedOperationError()

    def sync_resource(self, secrets: Secrets, resource: ResourceDescriptor) -> SyncSummary:  # noqa: ARG002
        raise UnsupportedOperationError()  # properties are imported by the analytics core

    # ------------------------------------------------------------------ reads (5-04, 5-05)
    def discover_resources(self, secrets: Secrets) -> list[ResourceDescriptor]:
        """Every GA4 property the person can reach (``accountSummaries``), grouped by its
        Analytics account, with its currency and time zone (``properties.get``, one call per
        property, at most ``MAX_PROPERTIES``). A property that cannot be read or used is
        listed with a plain reason (Q-5-3); entries that cannot be parsed are skipped and
        counted."""
        token = _token(secrets)
        found: dict[str, ResourceDescriptor] = {}
        skipped = 0
        for row in self.analytics.account_summaries(token):
            listed, unreadable = mapping.summaries(row)
            skipped += unreadable
            for summary in listed:
                if summary.id in found:
                    continue
                if len(found) >= MAX_PROPERTIES:
                    logger.warning(
                        "google_analytics_property_limit_reached", extra={"count": len(found)}
                    )
                    return list(found.values())
                try:
                    details: dict[str, Any] | None = self.analytics.get_property(token, summary.id)
                    reason = None
                except NoPropertyAccessError:
                    details, reason = None, "no_property_access"
                found[summary.id] = mapping.descriptor(summary, details, reason)
        if skipped:
            logger.warning("google_analytics_rows_skipped", extra={"count": skipped})
        return list(found.values())

    def read_property(self, secrets: Secrets, prop: AnalyticsPropertyRef) -> AnalyticsPropertyState:
        """The property's name, currency, time zone and status (one call)."""
        pid = valid_property_id(prop.external_id)
        state = mapping.property_state(pid, self.analytics.get_property(_token(secrets), pid))
        if state is None:
            raise UnexpectedResponseError()
        return state

    def read_daily(
        self, secrets: Secrets, prop: AnalyticsPropertyRef, first_day: date, last_day: date
    ) -> Iterator[AnalyticsDailyRecord]:
        """The three daily views of ``first_day`` … ``last_day`` (property time zone): one
        ``batchRunReports`` call holding all three, then ``runReport`` with ``offset`` for any
        view with more rows than a page, at most ``MAX_REPORT_PAGES`` pages a view (the rest is
        marked as truncated, never guessed)."""
        if first_day > last_day:
            raise ValueError("first_day must not be after last_day")
        pid, token = valid_property_id(prop.external_id), _token(secrets)
        views = list(mapping.VIEW_DIMENSIONS)
        reports = self.analytics.batch_run_reports(
            token, pid, [mapping.report_request(v, first_day, last_day) for v in views]
        )
        skipped = 0
        for view, report in zip(views, reports, strict=True):
            page = _parsed(view, report, first_day, last_day)
            records, quality, total, seen = (
                page.records,
                page.quality,
                page.row_count,
                page.rows_seen,
            )
            skipped += page.skipped
            pages = 1
            while seen < total and pages < MAX_REPORT_PAGES:
                request = mapping.report_request(view, first_day, last_day, offset=seen)
                more = _parsed(
                    view, self.analytics.run_report(token, pid, request), first_day, last_day
                )
                if more.rows_seen == 0:
                    break  # Google said there were more rows but sent none: stop, mark it
                records += more.records
                quality = mapping.merge_quality(quality, more.quality)
                seen, pages, skipped = seen + more.rows_seen, pages + 1, skipped + more.skipped
            if seen < total:
                quality = mapping.merge_quality(quality, AnalyticsQuality(truncated=True))
                logger.warning(
                    "google_analytics_report_truncated",
                    extra={"view": view.value, "rows": seen, "row_count": total},
                )
            for record in records:
                yield replace(record, quality=mapping.merge_quality(record.quality, quality))
        if skipped:
            logger.warning("google_analytics_rows_skipped", extra={"count": skipped})


def _parsed(
    view: AnalyticsBreakdown, report: dict[str, Any], first: date, last: date
) -> mapping.ParsedReport:
    parsed = mapping.parse_report(view, report, first, last)
    if parsed is None:
        raise UnexpectedResponseError()
    return parsed


def _token(secrets: Secrets) -> str:
    token = secrets.get("access_token")
    if not isinstance(token, str) or not token:
        raise SignInRejectedError()
    return token
