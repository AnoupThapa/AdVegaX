"""Budget amounts — computed by AdVegaX, never by the model (Phase 8, task 8-04, Q-8-5; D16).

The merchant sets one total, daily or monthly, in the reporting currency. The model proposes a
**share** (a percentage) per platform; AdVegaX:

1. checks the shares are positive and add up to 100 % (a rounding tolerance of 0.01 points, so
   three times 33.33 % is accepted);
2. computes each platform's amount in the currency's minor units with the **largest-remainder
   method**, so the amounts always add up to the total exactly;
3. checks each platform's **daily** amount (a monthly amount / 30.4, the average month) is at
   least that platform's minimum daily budget (``PLANNER_MIN_DAILY_<PLATFORM>_USD``, converted
   to the reporting currency with the latest rate). An unknown minimum is never assumed to be met.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal

from app.core.settings import Settings
from app.domains.finance.definitions import minor_units
from app.domains.fx.service import FxTable

HUNDRED = Decimal(100)
SHARE_TOLERANCE = Decimal("0.01")
DAYS_PER_MONTH = Decimal("30.4")
PERIODS = ("daily", "monthly")


@dataclass(frozen=True)
class Budget:
    amount: Decimal
    period: str  # daily | monthly
    currency: str

    def daily(self, amount: Decimal | None = None) -> Decimal:
        value = self.amount if amount is None else amount
        return value if self.period == "daily" else value / DAYS_PER_MONTH


def minimums(
    settings: Settings, fx: FxTable, currency: str, day: date
) -> dict[str, Decimal | None]:
    """Each platform's minimum daily budget in ``currency`` (None: no exchange rate)."""
    usd = {
        "google_ads": settings.PLANNER_MIN_DAILY_GOOGLE_ADS_USD,
        "meta_ads": settings.PLANNER_MIN_DAILY_META_ADS_USD,
    }
    return {p: fx.convert(amount, "USD", currency, day) for p, amount in usd.items()}


def _quantum(currency: str) -> Decimal:
    return Decimal(1).scaleb(-minor_units(currency))


def share_reasons(shares: dict[str, Decimal]) -> list[str]:
    reasons = [f"share_invalid:{p}" for p, s in shares.items() if not HUNDRED >= s > 0]
    if not reasons and abs(sum(shares.values(), Decimal(0)) - HUNDRED) > SHARE_TOLERANCE:
        reasons.append("shares_do_not_add_up")
    return reasons


def amounts(budget: Budget, shares: dict[str, Decimal]) -> dict[str, Decimal]:
    """Each platform's amount; together exactly ``budget.amount``. Shares must be valid."""
    quantum = _quantum(budget.currency)
    total_units = int((budget.amount / quantum).to_integral_value(ROUND_HALF_EVEN))
    weight = sum(shares.values(), Decimal(0))
    exact = {p: Decimal(total_units) * s / weight for p, s in shares.items()}
    units = {p: int(v.to_integral_value(ROUND_DOWN)) for p, v in exact.items()}
    left = total_units - sum(units.values())
    # The units left over go to the largest remainders (ties: the platform listed first).
    order = sorted(shares, key=lambda p: (-(exact[p] - units[p]), list(shares).index(p)))
    for platform in order[:left]:
        units[platform] += 1
    return {p: Decimal(units[p]) * quantum for p in shares}


def minimum_reasons(
    budget: Budget, split: dict[str, Decimal], minimums: dict[str, Decimal | None]
) -> list[str]:
    reasons = []
    for platform, amount in split.items():
        minimum = minimums.get(platform)
        if minimum is None:
            reasons.append(f"budget_minimum_not_checkable:{platform}")
        elif budget.daily(amount) < minimum:
            reasons.append(f"below_platform_minimum:{platform}")
    return reasons


def floor_reasons(
    budget: Budget, platforms: list[str], minimums: dict[str, Decimal | None]
) -> list[str]:
    """Before asking the model: can the total cover every platform's minimum at all?"""
    known = [minimums.get(p) for p in platforms]
    if any(m is None for m in known):
        return ["budget_minimum_not_checkable"]
    needed = sum((m for m in known if m is not None), Decimal(0))
    return ["budget_too_small"] if budget.daily() < needed else []


def out(budget: Budget, split: dict[str, Decimal]) -> dict[str, dict[str, str]]:
    """The stored form (``campaign_strategies.budget_amounts``): each platform's amount for the
    period and its daily equivalent, as strings in the currency's minor units."""
    quantum = _quantum(budget.currency)
    return {
        p: {
            "amount": str(a),
            "daily": str(budget.daily(a).quantize(quantum, rounding=ROUND_HALF_EVEN)),
        }
        for p, a in split.items()
    }
