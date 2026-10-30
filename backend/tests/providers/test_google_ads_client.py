"""Google sign-in and Google Ads REST client against the simulator (task 3-03, PLAN §4.1, §7)."""

from __future__ import annotations

import httpx
import pytest
from app.providers.base.errors import (
    AuthExpiredError,
    BlockedDestinationError,
    InvalidRequestError,
    RetryableError,
)
from app.providers.google_ads.client import (
    AccountNotEnabledError,
    BadQueryError,
    DeveloperTokenInvalidError,
    DeveloperTokenNotApprovedError,
    GoogleAdsClient,
    GoogleSignIn,
    NoAccountAccessError,
    NotAdsUserError,
    QuotaExhaustedError,
    SignInRejectedError,
    UnexpectedResponseError,
    raise_for_ads,
    valid_customer_id,
)
from app.providers.http.client import SafeHttpClient, SafeResponse

from tests.google_ads_sim import (
    API_VERSION,
    CLIENT_ID,
    CLIENT_SECRET,
    DEVELOPER_TOKEN,
    POLICY,
    GoogleAdsSim,
    sample_hierarchy,
)

SUB = "108000000000000000001"


@pytest.fixture
def sim(clock):
    return sample_hierarchy(GoogleAdsSim(clock=clock))


@pytest.fixture
def ads(sim):
    return GoogleAdsClient(sim.http_factory, API_VERSION, DEVELOPER_TOKEN)


@pytest.fixture
def token(sim):
    return sim._new_access(SUB)


def rows(n):
    return [{"customer": {"id": str(i)}} for i in range(n)]


# ------------------------------------------------------------------ requests
def test_list_accessible_customers_sends_the_required_headers(sim, ads, token):
    assert ads.list_accessible_customers(token) == ["9000000001", "1000000003", "1000000004"]
    (request,) = sim.calls("listAccessibleCustomers")
    assert request.url.host == "googleads.googleapis.com" or request.headers["host"] == (
        "googleads.googleapis.com"
    )
    assert request.url.path == f"/{API_VERSION}/customers:listAccessibleCustomers"
    assert request.headers["authorization"] == f"Bearer {token}"
    assert request.headers["developer-token"] == DEVELOPER_TOKEN
    assert "login-customer-id" not in request.headers
    assert token not in str(request.url) and DEVELOPER_TOKEN not in str(request.url)


def test_search_reaches_accounts_through_a_manager(sim, ads, token):
    sim.query_handler = lambda s, cid, q, login: [{"customer": {"id": cid}}]
    found = list(
        ads.search(
            token,
            "1000000001",
            "SELECT keyword_view.resource_name FROM keyword_view",
            login_customer_id="9000000001",
        )
    )
    assert found == [{"customer": {"id": "1000000001"}}]
    (request,) = sim.calls("googleAds:search")
    assert request.headers["login-customer-id"] == "9000000001"
    with pytest.raises(NoAccountAccessError):  # not reachable without the manager
        list(ads.search(token, "1000000001", "SELECT keyword_view.resource_name FROM keyword_view"))


def test_search_follows_page_tokens(sim, ads, token):
    sim.page_size = 3
    sim.query_handler = lambda *a: rows(7)
    assert (
        len(
            list(
                ads.search(
                    token, "1000000003", "SELECT keyword_view.resource_name FROM keyword_view"
                )
            )
        )
        == 7
    )
    bodies = [r.content for r in sim.calls("googleAds:search")]
    assert len(bodies) == 3 and b'"pageToken"' not in bodies[0] and b'"pageToken":"3"' in bodies[1]


def test_search_stream_reads_every_batch_in_one_request(sim, ads, token):
    sim.stream_batch_size = 2
    sim.query_handler = lambda *a: rows(5)
    assert (
        len(
            list(
                ads.search_stream(
                    token, "1000000003", "SELECT keyword_view.resource_name FROM keyword_view"
                )
            )
        )
        == 5
    )
    assert len(sim.calls("googleAds:searchStream")) == 1


def test_empty_answers_are_empty(sim, ads, token):
    assert (
        list(ads.search(token, "1000000003", "SELECT keyword_view.resource_name FROM keyword_view"))
        == []
    )
    assert (
        list(
            ads.search_stream(
                token, "1000000003", "SELECT keyword_view.resource_name FROM keyword_view"
            )
        )
        == []
    )


@pytest.mark.parametrize("bad", ["", "12a", "../9000000001", "1" * 21, "123/googleAds:mutate"])
def test_customer_ids_are_validated_before_use(ads, token, bad):
    with pytest.raises(InvalidRequestError):
        list(ads.search(token, bad, "SELECT keyword_view.resource_name FROM keyword_view"))
    with pytest.raises(InvalidRequestError):
        list(ads.search(token, "1000000003", "SELECT 1", login_customer_id=bad or "x"))


def test_dashes_in_customer_ids_are_accepted():
    assert valid_customer_id("123-456-7890") == "1234567890"


def test_the_api_version_is_validated(sim):
    with pytest.raises(ValueError, match="v25"):
        GoogleAdsClient(sim.http_factory, "2026-10", DEVELOPER_TOKEN)


# ------------------------------------------------------------------ errors
@pytest.mark.parametrize(
    ("status", "error_code", "expected"),
    [
        (401, {"authenticationError": "OAUTH_TOKEN_EXPIRED"}, AuthExpiredError),
        (401, {"authenticationError": "OAUTH_TOKEN_REVOKED"}, SignInRejectedError),
        (401, {"authenticationError": "DEVELOPER_TOKEN_INVALID"}, DeveloperTokenInvalidError),
        (403, {"authenticationError": "NOT_ADS_USER"}, NotAdsUserError),
        (403, {"authorizationError": "USER_PERMISSION_DENIED"}, NoAccountAccessError),
        (403, {"authorizationError": "CUSTOMER_NOT_ENABLED"}, AccountNotEnabledError),
        (
            403,
            {"authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"},
            DeveloperTokenNotApprovedError,
        ),
        (429, {"quotaError": "RESOURCE_EXHAUSTED"}, QuotaExhaustedError),
        (429, {"quotaError": "RESOURCE_TEMPORARILY_EXHAUSTED"}, QuotaExhaustedError),
        (400, {"queryError": "UNRECOGNIZED_FIELD"}, BadQueryError),
        (500, {"internalError": "INTERNAL_ERROR"}, RetryableError),
    ],
)
def test_google_ads_errors_become_plain_codes(sim, ads, token, status, error_code, expected):
    sim.fail_next.append((status, error_code))
    with pytest.raises(expected) as raised:
        list(ads.search(token, "1000000003", "SELECT keyword_view.resource_name FROM keyword_view"))
    assert "Simulated" not in str(raised.value)  # Google's message is never carried


def test_a_test_token_cannot_reach_production_accounts(sim, ads, token):
    sim.customers["1000000003"].test = False
    with pytest.raises(DeveloperTokenNotApprovedError):
        list(ads.search(token, "1000000003", "SELECT keyword_view.resource_name FROM keyword_view"))
    sim.token_access = "explorer"
    assert (
        list(ads.search(token, "1000000003", "SELECT keyword_view.resource_name FROM keyword_view"))
        == []
    )


def test_a_cancelled_account_is_not_enabled(ads, token):
    with pytest.raises(AccountNotEnabledError):
        list(ads.search(token, "1000000004", "SELECT keyword_view.resource_name FROM keyword_view"))


def test_a_person_without_google_ads_is_told_so(sim, ads):
    sim.add_user("108000000000000000002")
    with pytest.raises(NotAdsUserError):
        ads.list_accessible_customers(sim._new_access("108000000000000000002"))


def test_a_wrong_developer_token_is_refused(sim, token):
    other = GoogleAdsClient(sim.http_factory, API_VERSION, "wrong-token")
    with pytest.raises(DeveloperTokenInvalidError):
        other.list_accessible_customers(token)


def _response(status, content=b"", headers=None):
    return SafeResponse(status, httpx.Headers(headers or {}), content, "googleads.googleapis.com")


def test_quota_errors_carry_googles_retry_delay():
    body = (
        b'{"error":{"code":429,"details":[{"errors":[{"errorCode":{"quotaError":'
        b'"RESOURCE_TEMPORARILY_EXHAUSTED"},"details":{"quotaErrorDetails":'
        b'{"retryDelay":"30s"}}}]}]}}'
    )
    with pytest.raises(QuotaExhaustedError) as raised:
        raise_for_ads(_response(429, body))
    assert raised.value.retry_after_seconds == 30.0


@pytest.mark.parametrize(
    ("status", "expected"),
    [(301, UnexpectedResponseError), (401, AuthExpiredError), (429, QuotaExhaustedError)],
)
def test_unparseable_errors_fall_back_to_the_status(status, expected):
    with pytest.raises(expected):
        raise_for_ads(_response(status, b"<html>oops</html>"))


def test_non_json_answers_are_unexpected(sim, ads, token):
    sim.query_handler = lambda *a: rows(1)
    original = sim.handler

    def broken(request):
        response = original(request)
        return (
            httpx.Response(200, text="<html>proxy</html>")
            if "googleAds" in request.url.path
            else response
        )

    sim.handler = broken
    with pytest.raises(UnexpectedResponseError):
        list(ads.search(token, "1000000003", "SELECT keyword_view.resource_name FROM keyword_view"))


def test_only_google_hosts_are_called(clock):
    """The client never takes a host from anywhere: a private-address answer is refused."""
    sim = sample_hierarchy(GoogleAdsSim(clock=clock))

    def private():
        return SafeHttpClient(
            POLICY,
            resolver=lambda host, port: ["10.0.0.5"],
            transport=httpx.MockTransport(sim.handler),
        )

    with pytest.raises(BlockedDestinationError):
        GoogleAdsClient(private, API_VERSION, DEVELOPER_TOKEN).list_accessible_customers("t")


# ------------------------------------------------------------------ sign-in endpoints
def test_refused_grants_and_server_errors_at_the_token_endpoint(sim):
    sign_in = GoogleSignIn(sim.http_factory)
    form = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    with pytest.raises(SignInRejectedError):
        sign_in.token({**form, "grant_type": "refresh_token", "refresh_token": "unknown"})
    with pytest.raises(SignInRejectedError):  # wrong client secret
        sign_in.token({"client_id": CLIENT_ID, "client_secret": "x", "grant_type": "refresh_token"})
    sim.token_status = 503
    with pytest.raises(RetryableError):
        sign_in.token({**form, "grant_type": "refresh_token", "refresh_token": "unknown"})


def test_revoking_an_unknown_token_counts_as_revoked(sim):
    GoogleSignIn(sim.http_factory).revoke("not-a-token")  # no error
    assert sim.calls("/revoke")
