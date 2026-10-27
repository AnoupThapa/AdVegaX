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
