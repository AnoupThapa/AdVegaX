"""Meta Graph client and provider edge cases (task 4-02, PLAN §6-§7).

The read-only guard, ``appsecret_proof`` on every call, no token or secret in any address,
Meta's ``after`` cursor (never its ``next`` URL), Meta's error codes as plain codes, usage
headers, and the ``debug_token`` checks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

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
from app.providers.http.client import SafeHttpClient, SafeResponse
from app.providers.meta_ads import client as module
from app.providers.meta_ads.client import (
    BadQueryError,
    MetaGraphClient,
    MetaPermissionMissingError,
    MetaRateLimitedError,
    MetaSignInRejectedError,
    NoAccountAccessError,
    TooMuchDataError,
    UnexpectedResponseError,
    appsecret_proof,
    raise_for_meta,
    read_usage,
    valid_node,
)
from app.providers.meta_ads.provider import MetaAdsProvider

from tests.meta_sim import (
    API_VERSION,
    APP_ID,
    APP_SECRET,
    POLICY,
    PUBLIC_IP,
    MetaSim,
    build_provider,
    usage,
)

USER = "10160000000000001"


@pytest.fixture
def sim(clock):
    s = MetaSim(clock=clock)
    s.add_user(USER)
    return s


@pytest.fixture
def graph(sim):
    return MetaGraphClient(sim.http_factory, API_VERSION, APP_SECRET)


@pytest.fixture
def token(sim):
    return sim.new_token(USER)


def _answering(handler):
    return lambda: SafeHttpClient(
        POLICY, resolver=lambda host, port: [PUBLIC_IP], transport=httpx.MockTransport(handler)
    )


def _response(status, body=b"", headers=None):
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    return SafeResponse(status, httpx.Headers(headers or {}), content, "graph.facebook.com")


# ------------------------------------------------------------------ requests
def test_every_call_carries_the_proof_and_no_token_in_the_address(sim, graph, token):
    assert graph.get(token, "/me") == {"id": USER}
    (request,) = sim.calls("/me")
    assert request.url.host == "graph.facebook.com" or request.headers["host"] == (
        "graph.facebook.com"
    )
    assert request.url.path == f"/{API_VERSION}/me"
    assert request.headers["authorization"] == f"Bearer {token}"
    expected = hmac.new(APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
    assert request.url.params["appsecret_proof"] == expected == appsecret_proof(APP_SECRET, token)
    assert token not in str(request.url) and APP_SECRET not in str(request.url)


def test_a_wrong_proof_is_refused_by_meta(sim, token):
    other = MetaGraphClient(sim.http_factory, API_VERSION, "another-secret")
    with pytest.raises(BadQueryError):
        other.get(token, "/me")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/act_1/campaigns"),
        ("POST", "/act_1/adsets"),
        ("POST", "/123"),
        ("DELETE", "/123"),
        ("DELETE", "/act_1/campaigns"),
        ("PUT", "/act_1"),
        ("PATCH", "/act_1"),
        ("POST", "/act_1/insights/extra"),
    ],
)
def test_the_read_only_guard_refuses_anything_that_could_change_an_account(
    sim, graph, token, method, path
):
    with pytest.raises(ValueError, match="refused Meta call"):
        graph._send(method, path, token=token)
    assert sim.requests == []  # refused before anything was sent


@pytest.mark.parametrize("path", ["/me", "/act_123/insights", "/123456/insights"])
def test_the_documented_reads_and_writes_are_allowed(path):
    assert module._allowed("GET", path)
    assert module._allowed("POST", "/oauth/access_token")
    assert module._allowed("DELETE", "/me/permissions")
    assert module._allowed("POST", "/act_123/insights")


@pytest.mark.parametrize("bad", ["", "act_", "act_12a", "../123", "123/insights", "1" * 26])
def test_object_ids_are_validated(bad):
    with pytest.raises(InvalidRequestError):
        valid_node(bad)


def test_paths_are_validated(graph, token):
    for bad in ("me", "/me?x=1", "/a/b/c/d/e", "/../me", "/me/%2e%2e"):
        with pytest.raises(ValueError):
            graph._send("GET", bad, token=token)


def test_the_api_version_is_validated(sim):
    with pytest.raises(ValueError, match=r"v26\.0"):
        MetaGraphClient(sim.http_factory, "26", APP_SECRET)


# ------------------------------------------------------------------ paging
def _pages(sim, rows, page_size):
    def route(s, request, user_id):
        after = int(request.url.params.get("after", "0"))
        chunk = rows[after : after + page_size]
        body = {
            "data": chunk,
            "paging": {"cursors": {"before": "b", "after": str(after + len(chunk))}},
        }
        if after + page_size < len(rows):
            # Meta's own "next" address repeats the token: AdVegaX must not use it.
            body["paging"]["next"] = "https://graph.facebook.com/v26.0/me/things?access_token=X"
        return httpx.Response(200, json=body)

    sim.routes["GET /me/things"] = route


def test_lists_follow_the_after_cursor_never_the_next_address(sim, graph, token):
    _pages(sim, [{"id": str(i)} for i in range(7)], 3)
    assert [r["id"] for r in graph.get_all(token, "/me/things", {"limit": "3"})] == [
        str(i) for i in range(7)
    ]
    calls = sim.calls("/me/things")
    assert len(calls) == 3
    assert [c.url.params.get("after") for c in calls] == [None, "3", "6"]
    assert all("access_token" not in str(c.url) for c in calls)


def test_a_list_that_never_ends_is_stopped(sim, graph, token, monkeypatch):
    monkeypatch.setattr(module, "MAX_PAGES", 3)
    sim.routes["GET /me/things"] = lambda s, r, u: httpx.Response(
        200,
        json={"data": [{"id": "1"}], "paging": {"cursors": {"after": "x"}, "next": "https://n"}},
    )
    with pytest.raises(UnexpectedResponseError):
        list(graph.get_all(token, "/me/things"))


@pytest.mark.parametrize("body", [{"data": "rows"}, ["a list"], {"paging": {}}])
def test_odd_list_answers_are_unexpected(sim, graph, token, body):
    sim.routes["GET /me/things"] = lambda s, r, u: httpx.Response(200, json=body)
    with pytest.raises(UnexpectedResponseError):
        list(graph.get_all(token, "/me/things"))


def test_non_json_answers_are_unexpected(sim, graph, token):
    sim.routes["GET /me/things"] = lambda s, r, u: httpx.Response(200, text="<html>proxy</html>")
    with pytest.raises(UnexpectedResponseError):
        graph.get(token, "/me/things")


# ------------------------------------------------------------------ errors and usage
@pytest.mark.parametrize(
    ("status", "code", "subcode", "expected"),
    [
        (400, 190, 463, MetaSignInRejectedError),  # expired
        (400, 190, 460, MetaSignInRejectedError),  # password changed
        (400, 102, None, MetaSignInRejectedError),
        (403, 200, None, MetaPermissionMissingError),
        (400, 10, None, MetaPermissionMissingError),
        (400, 4, None, MetaRateLimitedError),
        (400, 17, None, MetaRateLimitedError),
        (400, 80004, None, MetaRateLimitedError),
        (400, 613, None, MetaRateLimitedError),
        (400, 100, 1487534, TooMuchDataError),
        (400, 100, 33, NoAccountAccessError),
        (400, 100, None, BadQueryError),
        (500, 1, None, RetryableError),
        (500, 2, None, RetryableError),
    ],
)
def test_metas_errors_become_plain_codes(sim, graph, token, status, code, subcode, expected):
    sim.fail_next.append((status, code, subcode))
    with pytest.raises(expected) as raised:
        graph.get(token, "/me")
    assert "Simulated" not in str(raised.value)  # Meta's message is never carried


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (301, UnexpectedResponseError),
        (401, MetaSignInRejectedError),
        (403, MetaPermissionMissingError),
        (404, Exception),
        (429, MetaRateLimitedError),
        (503, RetryableError),
        (418, InvalidRequestError),
    ],
)
def test_unparseable_errors_fall_back_to_the_status(status, expected):
    with pytest.raises(expected):
        raise_for_meta(_response(status, b"<html>oops</html>"))


def test_a_rate_limit_carries_metas_own_wait(sim, graph, token):
    sim.fail_next.append((400, 80004, 2446079))
    sim.usage_headers = usage(100, regain_minutes=7)
    with pytest.raises(MetaRateLimitedError) as raised:
        graph.get(token, "/me")
    assert raised.value.retry_after_seconds == 7 * 60


def test_usage_headers_are_read_on_every_answer(sim, graph, token):
    sim.usage_headers = usage(42, regain_minutes=0)
    graph.get(token, "/me")
    assert (graph.last_usage.percent, graph.last_usage.regain_seconds) == (42.0, None)
    assert graph.last_usage.access_tier == "development_access"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"x-app-usage": "not json"},
        {"x-business-use-case-usage": json.dumps({"act_1": "nope"})},
        {"x-fb-ads-insights-throttle": json.dumps({"app_id_util_pct": -5})},
        {"x-app-usage": "x" * 20_000},
    ],
)
def test_odd_usage_headers_count_as_nothing_used(headers):
    found = read_usage(httpx.Headers(headers))
    assert (found.percent, found.regain_seconds) == (0.0, None)


def test_the_highest_usage_counts():
    found = read_usage(
        httpx.Headers(
            {
                "x-app-usage": json.dumps({"call_count": 12, "total_time": 88}),
                "x-fb-ads-insights-throttle": json.dumps({"acc_id_util_pct": 30}),
            }
        )
    )
    assert found.percent == 88.0


# ------------------------------------------------------------------ provider
@pytest.fixture
def provider(sim):
    return build_provider(sim)


def test_all_three_settings_are_required(sim):
    with pytest.raises(ValueError, match="app id"):
        MetaAdsProvider(
            app_id="",
            app_secret="s",
            login_config_id="1",
            api_version=API_VERSION,
            http_factory=sim.http_factory,
            clock=sim.clock,
        )


def test_connect_takes_no_parameters(provider):
    assert provider.prepare_connect({}).params == {}
    with pytest.raises(InvalidConnectParamsError):
        provider.prepare_connect({"ad_account": "1"})


def test_pkce_is_required(provider):
    with pytest.raises(InvalidRequestError):
        provider.authorization_url(AuthorizationRequest(state="s", redirect_uri="https://x/cb"))


@pytest.mark.parametrize("params", [{}, {"code": ""}, {"code": "x" * 2049}])
def test_callbacks_without_a_usable_code_are_refused(provider, params):
    with pytest.raises(InvalidRequestError):
        provider.complete_authorization(
            params, redirect_uri="https://x/cb", code_verifier="v" * 43, provider_params={}
        )


def test_a_callback_without_the_verifier_is_refused(provider):
    with pytest.raises(InvalidRequestError):
        provider.complete_authorization(
            {"code": "c"}, redirect_uri="https://x/cb", code_verifier=None, provider_params={}
        )


def _meta_answers(me=None, permissions=None, exchange=None):
    """A Meta that answers the two exchanges, ``/me`` and ``/me/permissions``."""
    granted = [{"permission": "ads_read", "status": "granted"}]

    def handler(request):
        path = request.url.path
        if path.endswith("/me/permissions"):
            return httpx.Response(
                200, json={"data": granted if permissions is None else permissions}
            )
        if path.endswith("/me"):
            return httpx.Response(200, json={"id": USER} if me is None else me)
        body = {"access_token": "EAAtoken", "expires_in": 5_000_000}
        return httpx.Response(200, json=body if exchange is None else exchange)

    return handler


def _provider(handler, clock):
    return MetaAdsProvider(
        app_id=APP_ID,
        app_secret=APP_SECRET,
        login_config_id="1",
        api_version=API_VERSION,
        http_factory=_answering(handler),
        clock=clock,
    )


def _complete(provider):
    return provider.complete_authorization(
        {"code": "c"}, redirect_uri="https://x/cb", code_verifier="v" * 43, provider_params={}
    )


@pytest.mark.parametrize(
    ("answers", "error"),
    [
        ({"me": {"id": "not-digits"}}, MetaSignInRejectedError),
        ({"me": {}}, MetaSignInRejectedError),
        ({"me": {"id": 123}}, MetaSignInRejectedError),
        ({"me": {"id": "1" * 33}}, MetaSignInRejectedError),
        ({"permissions": [{"permission": 1, "status": "granted"}]}, UnexpectedResponseError),
        ({"permissions": [{"permission": "ads_read"}]}, UnexpectedResponseError),
        ({"permissions": [{"permission": "ads_read", "status": "declined"}]}, MissingScopesError),
        ({"permissions": []}, MissingScopesError),
    ],
)
def test_who_signed_in_and_what_they_granted_is_checked(clock, answers, error):
    with pytest.raises(error):
        _complete(_provider(_meta_answers(**answers), clock))


def test_the_token_expiry_comes_from_the_long_lived_exchange(clock):
    result = _complete(_provider(_meta_answers(), clock))
    assert result.token_expires_in_seconds == 5_000_000
    assert result.granted_scopes == ("ads_read",)
    assert result.external_account_id == USER


def test_a_token_meta_gives_without_an_expiry_has_none(clock):
    result = _complete(_provider(_meta_answers(exchange={"access_token": "EAAtoken"}), clock))
    assert result.token_expires_in_seconds is None


@pytest.mark.parametrize("answer", [{"token_type": "bearer"}, {"access_token": ""}])
def test_exchanges_without_a_token_are_refused(clock, answer):
    with pytest.raises(InvalidRequestError):
        _complete(_provider(_meta_answers(exchange=answer), clock))


def test_an_exchange_answer_that_is_not_an_object_is_unexpected(clock):
    provider = _provider(lambda request: httpx.Response(200, json=["x"]), clock)
    with pytest.raises(UnexpectedResponseError):
        provider.graph.exchange({"code": "c"})


def test_an_expired_token_is_refused_when_checked(sim, provider, clock):
    token = sim.new_token(USER)
    clock.advance(timedelta(days=61))
    with pytest.raises(MetaSignInRejectedError):
        provider.inspect(token)


def test_refreshing_is_not_possible_and_revoking_without_a_token_calls_nothing(sim, provider):
    with pytest.raises(UnsupportedOperationError):
        provider.refresh_credentials({"access_token": "x"})
    provider.revoke({})
    assert sim.requests == []


def test_revoking_a_token_meta_no_longer_knows_counts_as_done(sim, provider):
    provider.revoke({"access_token": "EAAunknown"})
    assert sim.calls("/me/permissions")


def test_operations_not_used_by_meta_or_not_built_yet(provider):
    from datetime import date

    from app.providers.base.types import AdAccountRef, AdLevel, ResourceDescriptor

    assert provider.discover_resources({}) == []  # task 4-03

    for call in (
        lambda: provider.verify_install({}),
        lambda: provider.parse_webhook({}, b""),
        lambda: provider.sync_resource({}, ResourceDescriptor(kind="ad_account", external_id="1")),
        lambda: provider.read_account({}, AdAccountRef("act_1")),
        lambda: provider.read_structure({}, AdAccountRef("act_1")),
        lambda: provider.read_performance(
            {}, AdAccountRef("act_1"), AdLevel.ACCOUNT, date(2026, 10, 1), date(2026, 10, 1)
        ),
    ):
        with pytest.raises(UnsupportedOperationError):
            call()


def test_entries_that_are_not_objects_are_skipped():
    found = read_usage(
        httpx.Headers(
            {"x-business-use-case-usage": json.dumps({"act_1": ["x", {"call_count": 5}]})}
        )
    )
    assert found.percent == 5.0


def test_an_unknown_error_code_falls_back_to_the_status():
    with pytest.raises(InvalidRequestError):
        raise_for_meta(_response(400, {"error": {"code": 368}}))


def test_list_rows_that_are_not_objects_are_skipped(sim, graph, token):
    sim.routes["GET /me/things"] = lambda s, r, u: httpx.Response(
        200, json={"data": ["x", {"id": "1"}]}
    )
    assert list(graph.get_all(token, "/me/things")) == [{"id": "1"}]
