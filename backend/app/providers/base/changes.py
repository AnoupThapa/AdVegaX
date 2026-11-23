"""Campaign changes at an advertising platform (Phase 10A, PHASE_10A_PLAN §3, Q-10A-1).

The **only** way AdVegaX changes an ad account is the Action Engine (``app/domains/actions``),
which reaches a platform through this interface. A provider that supports changes offers two
methods (``CampaignWriter``); their platform calls live in ``providers/<platform>/writes.py``
and nowhere else (static rule, tests/security).

* ``read_campaign`` — the campaign's status and budget as the platform sees them now: used
  before a change is requested, right before it is sent (a change approved on old information
  stops as stale) and afterwards to verify it.
* ``change_campaign`` — one change, as one platform operation. ``validate_only`` asks the
  platform to check it without changing anything (Google's ``validateOnly``, Meta's
  ``validate_only``).

Outcomes: success returns a ``ChangeReceipt`` (what was sent and a summary of the answer,
never a token). ``UnknownOutcomeError`` means the request may or may not have taken effect (a
timeout, a lost answer, a server error): the engine reads the campaign to find out and never
sends it again blindly. Any other ``ProviderError`` means the platform did not make the change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, cast

from app.providers.base.interfaces import PlatformProvider, Secrets
from app.providers.base.types import AdAccountRef, AdEntityStatus


class ChangeKind(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    SET_DAILY_BUDGET = "set_daily_budget"


@dataclass(frozen=True)
class CampaignSnapshot:
    """A campaign as the platform reports it now.

    ``status`` is the campaign's own setting (``None`` when the platform sent a value AdVegaX
    does not know); ``budget_level`` is ``campaign`` when the campaign holds its budget and
    ``ad_group`` when its ad sets do (Meta); ``daily_budget`` is the campaign's daily budget in
    the account currency (``None`` when it has none, e.g. a lifetime budget)."""

    external_id: str
    status: AdEntityStatus | None
    budget_level: str | None = None
    budget_period: str | None = None  # daily | lifetime
    daily_budget: Decimal | None = None
    budget_shared: bool = False
    budget_external_id: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "status": self.status.value if self.status else None,
            "budget_level": self.budget_level,
            "budget_period": self.budget_period,
            "daily_budget": str(self.daily_budget) if self.daily_budget is not None else None,
            "budget_shared": self.budget_shared,
        }


@dataclass(frozen=True)
class CampaignChange:
    kind: ChangeKind
    daily_budget: Decimal | None = None  # SET_DAILY_BUDGET: the new amount, account currency


@dataclass(frozen=True)
class ChangeReceipt:
    """What was sent (the platform method and fields, never a token) and a short summary of
    the platform's answer."""

    request: dict[str, Any] = field(default_factory=dict)
    answer: dict[str, Any] = field(default_factory=dict)


class CampaignWriter(PlatformProvider, Protocol):
    # Permissions a connection must hold before changes can be allowed (e.g. Meta's
    # ``ads_management``); empty when reading permissions already cover changes (Google).
    write_scopes: frozenset[str]

    def read_campaign(
        self, secrets: Secrets, account: AdAccountRef, campaign_id: str, currency: str
    ) -> CampaignSnapshot: ...

    def change_campaign(
        self,
        secrets: Secrets,
        account: AdAccountRef,
        snapshot: CampaignSnapshot,
        change: CampaignChange,
        currency: str,
        *,
        validate_only: bool,
    ) -> ChangeReceipt: ...


def campaign_writer(provider: PlatformProvider) -> CampaignWriter | None:
    """The provider as a ``CampaignWriter``, or None when it cannot change campaigns."""
    if not all(hasattr(provider, m) for m in ("read_campaign", "change_campaign", "write_scopes")):
        return None
    return cast(CampaignWriter, provider)


# ------------------------------------------------------------------ campaign builder (10B)
@dataclass(frozen=True)
class Keyword:
    text: str
    match: str  # phrase | exact | broad


@dataclass(frozen=True)
class CampaignBuild:
    """Everything one new campaign needs, checked by AdVegaX first (Phase 10B).

    ``reference`` (e.g. ``AVX-7F3A2C``) is part of every name, so a lost answer is looked up
    by it and never sent twice. Amounts are in the ad account's currency."""

    reference: str
    name: str
    daily_budget: Decimal
    locations: tuple[str, ...]  # ISO 3166-1 alpha-2 country codes from ``COUNTRIES``
    landing_url: str
    # Google (responsive search ad)
    keywords: tuple[Keyword, ...] = ()
    headlines: tuple[str, ...] = ()
    descriptions: tuple[str, ...] = ()
    path1: str = ""
    path2: str = ""
    maximize_conversions: bool = False  # otherwise maximize clicks
    # Meta (single image ad)
    primary_text: str = ""
    headline: str = ""
    description: str = ""
    call_to_action: str = ""
    image: bytes = field(default=b"", repr=False)
    page_id: str = ""
    pixel_id: str | None = None
    age_min: int = 18
    age_max: int = 65


@dataclass(frozen=True)
class BuildResult:
    """The platform IDs created (``campaign``, ``budget``, ``ad_group`` / ``ad_set``,
    ``creative``, ``ad``, ``image``) and what was sent (never a token)."""

    ids: dict[str, str] = field(default_factory=dict)
    request: dict[str, Any] = field(default_factory=dict)


class BuildIncomplete(Exception):
    """A launch stopped part-way (Meta builds step by step): ``ids`` were created — all
    paused — and ``cause`` is why it stopped (an ``UnknownOutcomeError`` when the last step's
    outcome is not known)."""

    def __init__(self, ids: dict[str, str], cause: Exception) -> None:
        super().__init__(getattr(cause, "code", "build_incomplete"))
        self.ids = dict(ids)
        self.cause = cause


@dataclass(frozen=True)
class MetaAsset:
    """A Facebook Page or a pixel (dataset) a person may choose."""

    id: str
    name: str | None


# Countries a campaign may target, with Google's geo target constant for each (the Google Ads
# API's geo targets list; to confirm in Step 0). More are added on request.
COUNTRIES: dict[str, int] = {
    "AU": 2036,
    "NZ": 2554,
    "NP": 2524,
    "IN": 2356,
    "US": 2840,
    "GB": 2826,
    "CA": 2124,
    "IE": 2372,
    "SG": 2702,
}


class CampaignBuilder(CampaignWriter, Protocol):
    def create_campaign(
        self,
        secrets: Secrets,
        account: AdAccountRef,
        build: CampaignBuild,
        currency: str,
        *,
        validate_only: bool,
    ) -> BuildResult:
        """Create the whole campaign **paused**. Google: one all-or-nothing request. Meta:
        step by step; a stop part-way raises ``BuildIncomplete`` with what exists."""
        ...

    def find_campaign(
        self, secrets: Secrets, account: AdAccountRef, reference: str
    ) -> dict[str, str]:
        """The objects whose name carries ``reference`` (empty: none). Read only."""
        ...

    def go_live(
        self, secrets: Secrets, account: AdAccountRef, ids: dict[str, str]
    ) -> ChangeReceipt:
        """Switch the created campaign (and Meta's ad set and ad) on."""
        ...

    def remove_objects(
        self, secrets: Secrets, account: AdAccountRef, ids: dict[str, str]
    ) -> ChangeReceipt:
        """Remove what a launch created (it is paused)."""
        ...


def campaign_builder(provider: PlatformProvider) -> CampaignBuilder | None:
    if campaign_writer(provider) is None:
        return None
    if not all(hasattr(provider, m) for m in ("create_campaign", "find_campaign", "go_live")):
        return None
    return cast(CampaignBuilder, provider)
