"""The platforms' change calls (Phase 10A, task 10A-03): what is sent, and how each outcome is
reported — success, a refusal, or an outcome that is unknown and must be looked up."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from app.core.clock import SystemClock
from app.providers.base.changes import CampaignChange, CampaignSnapshot, ChangeKind
from app.providers.base.errors import (
    InvalidRequestError,
    RateLimitedError,
    ResourceNotFoundError,
    UnknownOutcomeError,
)
from app.providers.base.types import AdAccountRef, AdEntityStatus
from app.providers.meta_ads import writes as meta
from app.providers.meta_ads.client import MetaGraphClient

from tests.google_ads_sim import GoogleAdsSim, build_provider, sample_hierarchy, sample_structure
from tests.meta_sim import APP_SECRET, MetaSim
from tests.meta_sim import sample_structure as meta_structure

AU = "1000000001"
SUB = "108000000000000000001"
REF = AdAccountRef(AU, "9000000001")
PAUSE = CampaignChange(ChangeKind.PAUSE)


@pytest.fixture
def gsim():
    s = sample_hierarchy(GoogleAdsSim(clock=SystemClock()))
    sample_structure(s.customers[AU])
    s.access_tokens["tok"] = (SUB, SystemClock().now().timestamp() + 3600)
    return s


@pytest.fixture
def gprovider(gsim):
    return build_provider(gsim)


def test_google_reads_one_campaign_with_its_budget(gsim, gprovider):
    found = gprovider.read_campaign({"access_token": "tok"}, REF, "11", "AUD")
    assert found == CampaignSnapshot(
        external_id="11",
        status=AdEntityStatus.ACTIVE,
        budget_level="campaign",
        budget_period="daily",
        daily_budget=Decimal(50),
        budget_shared=True,
        budget_external_id="501",
    )
    query = gsim.requests[-1].content.decode()
    assert "WHERE campaign.id = 11" in query
    with pytest.raises(ResourceNotFoundError):
        gprovider.read_campaign({"access_token": "tok"}, REF, "999", "AUD")
    with pytest.raises(InvalidRequestError):
        gprovider.read_campaign({"access_token": "tok"}, REF, "11 OR 1=1", "AUD")


def test_google_refuses_what_it_must_never_send(gprovider):
    shared = gprovider.read_campaign({"access_token": "tok"}, REF, "11", "AUD")
    budget = CampaignChange(ChangeKind.SET_DAILY_BUDGET, Decimal("60"))
    with pytest.raises(InvalidRequestError):  # a shared budget would change other campaigns
        gprovider.change_campaign(
            {"access_token": "tok"}, REF, shared, budget, "AUD", validate_only=True
        )
    own = CampaignSnapshot(
        "11", AdEntityStatus.ACTIVE, "campaign", "daily", Decimal(50), False, "501"
    )
    for amount in (Decimal("0"), Decimal("0.0000001")):
        with pytest.raises(InvalidRequestError):
            gprovider.change_campaign(
                {"access_token": "tok"},
                REF,
                own,
                CampaignChange(ChangeKind.SET_DAILY_BUDGET, amount),
                "AUD",
                validate_only=True,
            )
    with pytest.raises(InvalidRequestError):
        gprovider.change_campaign(
            {"access_token": "tok"},
            REF,
            own,
            CampaignChange(ChangeKind.SET_DAILY_BUDGET, None),
            "AUD",
            validate_only=True,
        )


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        ("timeout", UnknownOutcomeError),
        ("lose_answer", UnknownOutcomeError),
        ("server_error", UnknownOutcomeError),
    ],
)
def test_google_unknown_outcomes(gsim, gprovider, outcome, error):
    snapshot = gprovider.read_campaign({"access_token": "tok"}, REF, "11", "AUD")
    gsim.change_outcomes = [outcome]
    with pytest.raises(error):
        gprovider.change_campaign(
            {"access_token": "tok"}, REF, snapshot, PAUSE, "AUD", validate_only=False
        )


def test_google_rate_limits_and_answers_without_results(gsim, gprovider):
    snapshot = gprovider.read_campaign({"access_token": "tok"}, REF, "11", "AUD")
    gsim.fail_next = [(429, {"quotaError": "RESOURCE_EXHAUSTED"})]
    with pytest.raises(RateLimitedError):  # refused before anything happened
        gprovider.change_campaign(
            {"access_token": "tok"}, REF, snapshot, PAUSE, "AUD", validate_only=False
        )

    def empty(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":mutate"):
            return httpx.Response(200, json={})
        return gsim.handler(request)

    gprovider.ads._http_factory = lambda: _client(empty)
    with pytest.raises(UnknownOutcomeError):
        gprovider.change_campaign(
            {"access_token": "tok"}, REF, snapshot, PAUSE, "AUD", validate_only=False
        )
    receipt = gprovider.change_campaign(
        {"access_token": "tok"}, REF, snapshot, PAUSE, "AUD", validate_only=True
    )
    assert receipt.answer == {"results": 0} and receipt.request["validateOnly"] is True


def _client(handler):
    from app.providers.http.client import SafeHttpClient

    from tests.google_ads_sim import POLICY, PUBLIC_IP

    return SafeHttpClient(
        POLICY, resolver=lambda host, port: [PUBLIC_IP], transport=httpx.MockTransport(handler)
    )


# ------------------------------------------------------------------ Meta
@pytest.fixture
def msim():
    s = MetaSim(clock=SystemClock())
    s.add_user("1", "ads_read", "ads_management")
    meta_structure(s.add_account("act_1", "1", currency="AUD"))
    return s


@pytest.fixture
def graph(msim):
    return MetaGraphClient(msim.http_factory, "v26.0", APP_SECRET, sleep=lambda s: None)


@pytest.fixture
def token(msim):
    return msim.new_token("1")


def test_meta_reads_who_holds_the_budget(graph, token):
    own = meta.read_campaign(graph, token, "120001", "AUD")
    assert (own.budget_level, own.budget_period, own.daily_budget) == (
        "campaign",
        "daily",
        Decimal(50),
    )
    sets = meta.read_campaign(graph, token, "120002", "AUD")
    assert (sets.budget_level, sets.daily_budget, sets.status) == (
        "ad_group",
        None,
        AdEntityStatus.PAUSED,
    )
    with pytest.raises(InvalidRequestError):
        meta.read_campaign(graph, token, "act_1", "AUD")


def test_meta_never_sends_a_budget_the_campaign_does_not_hold(graph, token):
    sets = meta.read_campaign(graph, token, "120002", "AUD")
    with pytest.raises(InvalidRequestError):
        meta.change_campaign(
            graph,
            token,
            sets,
            CampaignChange(ChangeKind.SET_DAILY_BUDGET, Decimal(20)),
            "AUD",
            validate_only=True,
        )
    own = meta.read_campaign(graph, token, "120001", "AUD")
    with pytest.raises(InvalidRequestError):  # not a whole number of cents
        meta.change_campaign(
            graph,
            token,
            own,
            CampaignChange(ChangeKind.SET_DAILY_BUDGET, Decimal("1.005")),
            "AUD",
            validate_only=True,
        )


def test_meta_budget_units_and_outcomes(graph, token, msim):
    own = meta.read_campaign(graph, token, "120001", "AUD")
    receipt = meta.change_campaign(
        graph,
        token,
        own,
        CampaignChange(ChangeKind.SET_DAILY_BUDGET, Decimal("12.34")),
        "AUD",
        validate_only=False,
    )
    assert receipt.request == {"method": "POST /<campaign>", "daily_budget": "1234"}
    assert msim.mutations == [{"id": "120001", "daily_budget": "1234"}]
    msim.change_outcomes = ["timeout"]
    with pytest.raises(UnknownOutcomeError):
        meta.change_campaign(graph, token, own, PAUSE, "AUD", validate_only=False)


def test_the_meta_change_path_is_guarded(graph, token):
    with pytest.raises(ValueError, match="refused Meta call"):
        graph._send("POST", "/act_1/users", token=token, form={}, change=True)
    with pytest.raises(ValueError, match="refused Meta call"):
        graph._send("POST", "/120001", token=token, form={})  # not through the change path
    with pytest.raises(InvalidRequestError):
        graph.post_change(token, "act_1", {})
    with pytest.raises(ValueError, match="refused Meta call"):
        graph._send("DELETE", "/act_1/campaigns", token=token, form={}, change=True)
    with pytest.raises(InvalidRequestError):
        graph.post_create(token, "act_1", "users", {})
