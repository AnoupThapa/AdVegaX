"""Google Analytics client and provider edge cases (task 5-03, PLAN §6-§7).

The read-only guard, the token only in the header, Google's errors as plain codes, the quota
block, ``nextPageToken`` paging, property id checks, and the shared Google sign-in.
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.providers.base.errors import (
    InvalidConnectParamsError,
    InvalidRequestError,
    MissingScopesError,
    RetryableError,
    UnsupportedOperationError,
)
from app.providers.base.types import AuthorizationRequest
from app.providers.google.oauth import SignInRejectedError, UnexpectedResponseError
from app.providers.google_analytics.client import (
    AnalyticsApiDisabledError,
    AnalyticsPermissionMissingError,
    BadQueryError,
    GoogleAnalyticsClient,
    NoPropertyAccessError,
    PropertyQuotaError,
    Quota,
    _allowed,
    read_quota,
    valid_property_id,
)
from app.providers.google_analytics.provider import ANALYTICS_SCOPE, GoogleAnalyticsProvider
from app.providers.http.client import SafeHttpClient

from tests.ga4_sim import API_VERSION, POLICY, PUBLIC_IP, GA4Sim, build_provider
from tests.google_oauth_sim import CLIENT_ID, CLIENT_SECRET

SUB = "108000000000000000077"


@pytest.fixture
def sim(clock):
    s = GA4Sim(clock=clock)
    s.add_property("111", "900", SUB, display_name="Eve Zone AU")
    return s


@pytest.fixture
def token(sim):
    """A signed-in Google account with ``analytics.readonly``."""
    refresh = "1//sim-refresh-test"
    sim.refresh_tokens[refresh] = SUB
    sim.refresh_scopes[refresh] = f"{ANALYTICS_SCOPE} openid"
    return sim._new_access(SUB)


@pytest.fixture
def ga(sim):
    return GoogleAnalyticsClient(sim.http_factory, API_VERSION)


def _answering(handler):
    return lambda: SafeHttpClient(
        POLICY, resolver=lambda host, port: [PUBLIC_IP], transport=httpx.MockTransport(handler)
    )


# ------------------------------------------------------------------ read-only guard
@pytest.mark.parametrize(
    ("host", "method", "path", "allowed"),
    [
        ("analyticsadmin.googleapis.com", "GET", "/v1beta/accountSummaries", True),
        ("analyticsadmin.googleapis.com", "GET", "/v1beta/properties/111", True),
        ("analyticsdata.googleapis.com", "POST", "/v1beta/properties/111:runReport", True),
        ("analyticsdata.googleapis.com", "POST", "/v1beta/properties/111:batchRunReports", True),
        ("analyticsdata.googleapis.com", "GET", "/v1beta/properties/111/metadata", True),
        ("analyticsadmin.googleapis.com", "PATCH", "/v1beta/properties/111", False),
        ("analyticsadmin.googleapis.com", "DELETE", "/v1beta/properties/111", False),
        ("analyticsadmin.googleapis.com", "POST", "/v1beta/properties", False),
        ("analyticsadmin.googleapis.com", "GET", "/v1beta/properties/111/dataStreams", False),
        ("analyticsdata.googleapis.com", "POST", "/v1beta/properties/111:runAccessReport", False),
        ("analyticsdata.googleapis.com", "POST", "/v1beta/properties/111:runRealtimeReport", False),
        ("analyticsdata.googleapis.com", "POST", "/v1alpha/properties/111:runReport", False),
        ("analyticsdata.googleapis.com", "POST", "/v1beta/properties/1x:runReport", False),
        ("evil.example.com", "GET", "/v1beta/accountSummaries", False),
    ],
)
def test_only_reads_are_allowed(host, method, path, allowed):
    assert _allowed(host, method, path, "v1beta") is allowed


def test_a_refused_call_is_never_sent(sim, ga, token):
    with pytest.raises(ValueError, match="refused"):
        ga._send("PATCH", "analyticsadmin.googleapis.com", "/v1beta/properties/111", token=token)
    assert sim.requests == []


def test_the_token_travels_only_in_the_header(sim, ga, token):
    list(ga.account_summaries(token))
    ga.get_property(token, "properties/111")
    for request in sim.requests:
        assert request.headers["authorization"] == f"Bearer {token}"
        assert token not in str(request.url)


# ------------------------------------------------------------------ admin reads
def test_account_summaries_are_read_page_by_page(sim, ga, token):
    for n in range(5):
        sim.add_property(str(200 + n), str(800 + n), SUB, display_name=f"Shop {n}")
    sim.page_size_cap = 2
    rows = list(ga.account_summaries(token))
    assert len(rows) == 6
    pages = [r for r in sim.requests if r.url.path.endswith("/accountSummaries")]
    assert len(pages) == 3
    assert "pageToken" not in pages[0].url.query.decode()


def test_a_page_that_never_ends_is_stopped(ga, token, monkeypatch):
    from app.providers.google_analytics import client as module

    monkeypatch.setattr(module, "MAX_PAGES", 2)
    endless = GoogleAnalyticsClient(
        _answering(
            lambda r: httpx.Response(200, json={"accountSummaries": [], "nextPageToken": "x"})
        ),
        API_VERSION,
    )
    with pytest.raises(UnexpectedResponseError):
        list(endless.account_summaries(token))


def test_odd_summary_answers_are_refused(token):
    odd = GoogleAnalyticsClient(
        _answering(lambda r: httpx.Response(200, json={"accountSummaries": "x"})), API_VERSION
    )
    with pytest.raises(UnexpectedResponseError):
        list(odd.account_summaries(token))
    not_json = GoogleAnalyticsClient(
        _answering(lambda r: httpx.Response(200, text="<html>")), API_VERSION
    )
    with pytest.raises(UnexpectedResponseError):
        not_json.get_property(token, "111")
    listed = GoogleAnalyticsClient(_answering(lambda r: httpx.Response(200, json=[1])), API_VERSION)
    with pytest.raises(UnexpectedResponseError):
        listed.get_property(token, "111")


def test_property_ids_are_checked(ga, token, sim):
    assert valid_property_id("properties/111") == valid_property_id("111") == "111"
    for bad in ("", "properties/", "properties/1/../2", "accounts/1", "111?x=1", "1" * 21):
        with pytest.raises(InvalidRequestError):
            valid_property_id(bad)
    with pytest.raises(InvalidRequestError):
        ga.get_property(token, "../accountSummaries")
    assert sim.requests == []


def test_a_property_without_access_is_explained(ga, token):
    with pytest.raises(NoPropertyAccessError) as caught:
        ga.get_property(token, "999")
    assert caught.value.code == "no_property_access"


# ------------------------------------------------------------------ reports and quota
def test_reports_ask_for_the_quota_and_keep_it(sim, ga, token):
    reports = ga.batch_run_reports(token, "111", [{"dateRanges": []}, {"dateRanges": []}])
    assert len(reports) == 2
    (call,) = sim.calls(":batchRunReports")
    sent = json.loads(call.content)
    assert all(r["returnPropertyQuota"] is True for r in sent["requests"])
    assert ga.last_quota == Quota(
        day_remaining=200_000 - 10,
        hour_remaining=40_000 - 10,
        project_hour_remaining=14_000 - 10,
        concurrent_remaining=10,
    )
    single = ga.run_report(token, "111", {"dateRanges": []})
    assert "propertyQuota" in single and ga.last_quota.day_remaining == 200_000 - 30


def test_a_batch_holds_one_to_five_reports(ga, token):
    for size in (0, 6):
        with pytest.raises(ValueError, match="1 to 5"):
            ga.batch_run_reports(token, "111", [{}] * size)


def test_a_batch_answer_with_the_wrong_number_of_reports_is_refused(token):
    short = GoogleAnalyticsClient(
        _answering(lambda r: httpx.Response(200, json={"reports": [{}]})), API_VERSION
    )
    with pytest.raises(UnexpectedResponseError):
        short.batch_run_reports(token, "111", [{}, {}])
    odd = GoogleAnalyticsClient(
        _answering(lambda r: httpx.Response(200, json={"reports": [1]})), API_VERSION
    )
    with pytest.raises(UnexpectedResponseError):
        odd.batch_run_reports(token, "111", [{}])


@pytest.mark.parametrize(
    "block",
    [
        None,
        {},
        {"tokensPerDay": "x"},
        {"tokensPerDay": {"remaining": -1}},
        {"tokensPerDay": {"remaining": True}},
    ],
)
def test_odd_quota_blocks_are_ignored(block):
    found = read_quota({"propertyQuota": block} if block is not None else {})
    assert found is None or found.day_remaining is None


def test_the_quota_is_read_from_the_first_report_of_a_batch():
    found = read_quota({"reports": [{"propertyQuota": {"tokensPerHour": {"remaining": 7}}}]})
    assert found == Quota(hour_remaining=7)


# ------------------------------------------------------------------ Google's errors
@pytest.mark.parametrize(
    ("status", "state", "reason", "expected", "code"),
    [
        (401, "UNAUTHENTICATED", None, SignInRejectedError, "google_sign_in_rejected"),
        (
            403,
            "PERMISSION_DENIED",
            "SERVICE_DISABLED",
            AnalyticsApiDisabledError,
            "analytics_api_disabled",
        ),
        (
            403,
            "PERMISSION_DENIED",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
            AnalyticsPermissionMissingError,
            "analytics_permission_missing",
        ),
        (403, "PERMISSION_DENIED", None, NoPropertyAccessError, "no_property_access"),
        (404, "NOT_FOUND", None, NoPropertyAccessError, "no_property_access"),
        (429, "RESOURCE_EXHAUSTED", None, PropertyQuotaError, "rate_limited"),
        (400, "INVALID_ARGUMENT", None, BadQueryError, "bad_query"),
        (500, "INTERNAL", None, RetryableError, "retryable"),
        (503, "UNAVAILABLE", None, RetryableError, "retryable"),
        (409, "ABORTED", None, InvalidRequestError, "invalid_request"),
    ],
)
def test_googles_errors_become_plain_codes(sim, ga, token, status, state, reason, expected, code):
    sim.fail_next.append((status, state, reason))
    with pytest.raises(expected) as caught:
        ga.get_property(token, "111")
    assert caught.value.code == code
    assert "Simulated" not in str(caught.value)  # Google's message never travels on


def test_a_quota_error_pauses_only_that_property():
    from app.providers.base.errors import AccountBusyError

    assert issubclass(PropertyQuotaError, AccountBusyError)


def test_a_disabled_api_is_a_set_up_problem(sim, ga, token):
    sim.api_enabled = False
    with pytest.raises(AnalyticsApiDisabledError):
        list(ga.account_summaries(token))


def test_unknown_or_expired_tokens_are_refused(sim, ga, clock):
    from datetime import timedelta

    with pytest.raises(SignInRejectedError):
        ga.get_property("ya29.unknown", "111")
    refresh = "1//r"
    sim.refresh_tokens[refresh] = SUB
    sim.refresh_scopes[refresh] = ANALYTICS_SCOPE
    stale = sim._new_access(SUB)
    clock.advance(timedelta(hours=2))
    with pytest.raises(SignInRejectedError):
        ga.get_property(stale, "111")


def test_redirects_and_unreadable_errors_are_handled(token):
    moved = GoogleAnalyticsClient(
        _answering(lambda r: httpx.Response(302, headers={"location": "https://evil.example.com"})),
        API_VERSION,
    )
    with pytest.raises(UnexpectedResponseError):
        moved.get_property(token, "111")
    html = GoogleAnalyticsClient(
        _answering(lambda r: httpx.Response(502, text="<html>")), API_VERSION
    )
    with pytest.raises(RetryableError):
        html.get_property(token, "111")


def test_only_stable_versions(sim):
    for version in ("v1beta", "v1"):
        assert GoogleAnalyticsClient(sim.http_factory, version).version == version
    for bad in ("v1alpha", "v2", "beta", ""):
        with pytest.raises(ValueError):
            GoogleAnalyticsClient(sim.http_factory, bad)


# ------------------------------------------------------------------ the provider
def test_the_provider_asks_only_for_analytics_readonly(sim):
    provider = build_provider(sim)
    url = provider.authorization_url(
        AuthorizationRequest(
            state="s", redirect_uri="https://app.example/cb", code_challenge="c" * 43
        )
    )
    query = dict(httpx.URL(url).params)
    assert query["scope"] == f"{ANALYTICS_SCOPE} openid"
    assert "adwords" not in url and "analytics.edit" not in url
    assert (query["access_type"], query["code_challenge_method"]) == ("offline", "S256")
    assert query["include_granted_scopes"] == "false"


def test_pkce_is_required_and_nothing_is_typed(sim):
    provider = build_provider(sim)
    with pytest.raises(InvalidRequestError):
        provider.authorization_url(
            AuthorizationRequest(state="s", redirect_uri="https://a/cb", code_challenge=None)
        )
    with pytest.raises(InvalidConnectParamsError):
        provider.prepare_connect({"property": "1"})
    assert provider.prepare_connect({}) is not None


def test_a_sign_in_without_the_analytics_permission_is_refused(sim):
    provider = build_provider(sim)
    with pytest.raises(MissingScopesError):
        provider.complete_authorization(
            {"code": "x", "scope": "openid"},
            redirect_uri="https://a/cb",
            code_verifier="v" * 43,
            provider_params={},
        )


def test_the_provider_needs_its_client(sim, clock):
    with pytest.raises(ValueError, match="client id"):
        GoogleAnalyticsProvider(
            client_id="",
            client_secret=CLIENT_SECRET,
            api_version=API_VERSION,
            http_factory=sim.http_factory,
            clock=clock,
        )
    assert CLIENT_ID


def test_operations_not_used_by_ga4_or_not_built_yet(sim):
    from datetime import date

    from app.providers.base.types import AnalyticsPropertyRef, ResourceDescriptor

    provider = build_provider(sim)
    with pytest.raises(SignInRejectedError):  # discovery needs a token (task 5-04)
        provider.discover_resources({})
    with pytest.raises(SignInRejectedError):
        provider.read_property({}, AnalyticsPropertyRef("111"))
    with pytest.raises(SignInRejectedError):  # daily reports need a token too (task 5-05)
        list(
            provider.read_daily(
                {}, AnalyticsPropertyRef("111"), date(2026, 10, 1), date(2026, 10, 1)
            )
        )
    for call in (
        lambda: provider.verify_install({}),
        lambda: provider.parse_webhook({}, b""),
        lambda: provider.sync_resource(
            {}, ResourceDescriptor(kind="analytics_property", external_id="1")
        ),
    ):
        with pytest.raises(UnsupportedOperationError):
            call()
