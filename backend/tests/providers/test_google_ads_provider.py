"""Google Ads provider edge cases: sign-in checks, ID token rules, refresh, revoke (task 3-03)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from app.providers.base.errors import (
    AuthExpiredError,
    InvalidConnectParamsError,
    InvalidRequestError,
    MissingScopesError,
    RateLimitedError,
    RetryableError,
    UnsupportedOperationError,
)
from app.providers.base.types import AuthorizationRequest, ResourceDescriptor
from app.providers.google_ads.client import (
    GoogleAdsClient,
    GoogleSignIn,
    SignInRejectedError,
    UnexpectedResponseError,
    _retry_delay,
)
from app.providers.google_ads.provider import ADS_SCOPE, GoogleAdsProvider, _positive_int
from app.providers.http.client import SafeHttpClient

from tests.google_ads_sim import (
    API_VERSION,
    CLIENT_ID,
    DEVELOPER_TOKEN,
    POLICY,
    PUBLIC_IP,
    GoogleAdsSim,
    build_provider,
    sample_hierarchy,
)

SUB = "108000000000000000001"


@pytest.fixture
def sim(clock):
    return sample_hierarchy(GoogleAdsSim(clock=clock))


@pytest.fixture
def provider(sim):
    return build_provider(sim)


def _jwt(claims):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


def _claims(clock, **changes):
    base = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": SUB,
        "exp": int(clock.now().timestamp()) + 600,
    }
    return {**base, **changes}


def _answering(handler):
    return lambda: SafeHttpClient(
        POLICY, resolver=lambda host, port: [PUBLIC_IP], transport=httpx.MockTransport(handler)
    )


# ------------------------------------------------------------------ construction and start
def test_all_three_secrets_are_required(sim):
    with pytest.raises(ValueError, match="client id"):
        GoogleAdsProvider(
            client_id="",
            client_secret="s",
            developer_token="d",
            api_version=API_VERSION,
            http_factory=sim.http_factory,
            clock=sim.clock,
        )


def test_connect_takes_no_parameters(provider):
    assert provider.prepare_connect({}).params == {}
    with pytest.raises(InvalidConnectParamsError):
        provider.prepare_connect({"customer_id": "1"})


def test_pkce_is_required(provider):
    with pytest.raises(InvalidRequestError):
        provider.authorization_url(AuthorizationRequest(state="s", redirect_uri="https://x/cb"))


# ------------------------------------------------------------------ callback checks
@pytest.mark.parametrize(
    "params",
    [{}, {"code": "", "scope": ADS_SCOPE}, {"code": "x" * 1025, "scope": ADS_SCOPE}],
)
def test_callbacks_without_a_usable_code_are_refused(provider, params):
    with pytest.raises(InvalidRequestError):
        provider.complete_authorization(
            params, redirect_uri="https://x/cb", code_verifier="v" * 43, provider_params={}
        )


def test_a_callback_without_the_verifier_is_refused(provider):
    with pytest.raises(InvalidRequestError):
        provider.complete_authorization(
            {"code": "c", "scope": ADS_SCOPE},
            redirect_uri="https://x/cb",
            code_verifier=None,
            provider_params={},
        )


def _token_answer(body):
    return _answering(lambda request: httpx.Response(200, json=body))


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"refresh_token": "r", "scope": ADS_SCOPE}, InvalidRequestError),  # no access token
        ({"access_token": "a", "scope": ADS_SCOPE}, InvalidRequestError),  # no refresh token
        ({"access_token": "a", "refresh_token": "r", "scope": "openid"}, MissingScopesError),
    ],
)
def test_incomplete_token_answers_are_refused(sim, body, error):
    provider = GoogleAdsProvider(
        client_id=CLIENT_ID,
        client_secret="s",
        developer_token="d",
        api_version=API_VERSION,
        http_factory=_token_answer(body),
        clock=sim.clock,
    )
    with pytest.raises(error):
        provider.complete_authorization(
            {"code": "c", "scope": ADS_SCOPE},
            redirect_uri="https://x/cb",
            code_verifier="v" * 43,
            provider_params={},
        )


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://evil.example"},
        {"aud": "another-client"},
        {"exp": 1},
        {"exp": "soon"},
        {"sub": "not-digits"},
        {"sub": "1" * 65},
        {"sub": None},
    ],
)
def test_id_tokens_must_be_googles_and_for_advegax(provider, clock, change):
    with pytest.raises(InvalidRequestError):
        provider._subject(_jwt(_claims(clock, **change)))


@pytest.mark.parametrize("bad", [None, "", "a.b", "a.!!!.c", f"a.{'x' * 9000}.c", "a.WyJ4Il0.c"])
def test_malformed_id_tokens_are_refused(provider, bad):
    with pytest.raises(InvalidRequestError):
        provider._subject(bad)


def test_a_valid_id_token_gives_the_google_account_id(provider, clock):
    assert provider._subject(_jwt(_claims(clock))) == SUB
    assert provider._subject(_jwt(_claims(clock, iss="accounts.google.com"))) == SUB


# ------------------------------------------------------------------ refresh and revoke
def test_refresh_needs_a_refresh_token(provider):
    with pytest.raises(AuthExpiredError):
        provider.refresh_credentials({"access_token": "a"})


def test_refresh_answers_without_an_access_token_are_rejections(sim):
    provider = GoogleAdsProvider(
        client_id=CLIENT_ID,
        client_secret="s",
        developer_token="d",
        api_version=API_VERSION,
        http_factory=_token_answer({"expires_in": 3599}),
        clock=sim.clock,
    )
    with pytest.raises(SignInRejectedError):
        provider.refresh_credentials({"refresh_token": "r"})


def test_a_malformed_refresh_request_is_a_rejection(sim):
    provider = GoogleAdsProvider(
        client_id=CLIENT_ID,
        client_secret="s",
        developer_token="d",
        api_version=API_VERSION,
        http_factory=_answering(lambda r: httpx.Response(400, json={"error": "invalid_request"})),
        clock=sim.clock,
    )
    with pytest.raises(SignInRejectedError):
        provider.refresh_credentials({"refresh_token": "r"})


def test_revoke_without_tokens_calls_nothing(sim, provider):
    provider.revoke({})
    assert sim.requests == []


def test_revoke_falls_back_to_the_access_token(sim, provider):
    token = sim._new_access(SUB)
    provider.revoke({"access_token": token})
    assert token in sim.revoked


@pytest.mark.parametrize(
    ("status", "error"), [(503, RetryableError), (429, RetryableError), (403, InvalidRequestError)]
)
def test_revoke_failures(status, error):
    sign_in = GoogleSignIn(_answering(lambda r: httpx.Response(status)))
    with pytest.raises(error):
        sign_in.revoke("t")


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (429, {}, RateLimitedError),
        (404, {}, InvalidRequestError),
        (200, ["not", "an", "object"], UnexpectedResponseError),
        (401, {"error": "something_else"}, InvalidRequestError),
    ],
)
def test_token_endpoint_answers(status, body, error):
    sign_in = GoogleSignIn(_answering(lambda r: httpx.Response(status, json=body)))
    with pytest.raises(error):
        sign_in.token({"grant_type": "refresh_token"})


def test_an_empty_400_from_the_token_endpoint_is_a_bad_request():
    sign_in = GoogleSignIn(_answering(lambda r: httpx.Response(400)))
    with pytest.raises(InvalidRequestError):
        sign_in.token({})


# ------------------------------------------------------------------ not supported here
def test_operations_google_ads_does_not_support(provider):
    for call in (
        lambda: provider.verify_install({}),
        lambda: provider.parse_webhook({}, b""),
        lambda: provider.sync_resource({}, ResourceDescriptor(kind="ad_account", external_id="1")),
    ):
        with pytest.raises(UnsupportedOperationError):
            call()


def test_positive_int():
    assert (_positive_int("3599"), _positive_int(0), _positive_int(None), _positive_int("x")) == (
        3599,
        None,
        None,
        None,
    )


# ------------------------------------------------------------------ odd Google Ads answers
def _ads(handler):
    return GoogleAdsClient(_answering(handler), API_VERSION, DEVELOPER_TOKEN)


@pytest.mark.parametrize(
    "body",
    [{"resourceNames": "customers/1"}, {"resourceNames": ["accounts/1"]}, {"resourceNames": [7]}],
)
def test_odd_account_lists_are_unexpected(body):
    with pytest.raises(UnexpectedResponseError):
        _ads(lambda r: httpx.Response(200, json=body)).list_accessible_customers("t")


def test_an_account_list_without_names_is_empty():
    assert _ads(lambda r: httpx.Response(200, json={})).list_accessible_customers("t") == []


@pytest.mark.parametrize(
    "body",
    [["a list"], {"results": "rows"}, {"results": [], "nextPageToken": "x" * 5000}],
)
def test_odd_search_pages_are_unexpected(body):
    with pytest.raises(UnexpectedResponseError):
        list(_ads(lambda r: httpx.Response(200, json=body)).search("t", "1", "SELECT 1"))


def test_a_search_that_never_ends_is_stopped(monkeypatch):
    from app.providers.google_ads import client as module

    monkeypatch.setattr(module, "MAX_PAGES", 3)
    answer = {"results": [{"a": 1}], "nextPageToken": "next"}
    with pytest.raises(UnexpectedResponseError):
        list(_ads(lambda r: httpx.Response(200, json=answer)).search("t", "1", "SELECT 1"))


def test_a_stream_sent_as_one_object_is_read():
    answer = {"results": [{"a": 1}, "not a row"]}
    rows = list(
        _ads(lambda r: httpx.Response(200, json=answer)).search_stream("t", "1", "SELECT 1")
    )
    assert rows == [{"a": 1}]


def test_a_stream_that_is_not_json_rows_is_unexpected():
    with pytest.raises(UnexpectedResponseError):
        list(_ads(lambda r: httpx.Response(200, json="text")).search_stream("t", "1", "SELECT 1"))


def test_unusable_retry_delays_are_ignored():
    def detail(value):
        return [{"errors": [{"details": {"quotaErrorDetails": {"retryDelay": value}}}]}]

    assert _retry_delay(detail("soon")) is None
    assert _retry_delay(detail("xs")) is None
    assert _retry_delay(["not a dict", {"errors": [None]}]) is None
