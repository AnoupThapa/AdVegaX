"""Keeping exchange rates and converting with them (Phase 6, task 6-03, Q-6-3, Q-6-12).

**Refresh** (a scheduled task, every ``SCHEDULE_FX_INTERVAL``): for each source, the first run
reads ``FX_HISTORY_WINDOW`` (enough for 13 months of figures); later runs read again from
``FX_REFRESH_DAYS`` before the newest stored day, so a late or corrected publication is picked
up. Rows are upserted as published, through the system role (the only writer). One source
failing never stops the other.

**Conversion** (``FxTable``), in one place:

* the same currency needs no rate;
* each figure uses **its own day's** rate; on a weekend or holiday, the **last published** rate
  before it, at most ``FX_MAX_STALE_DAYS`` old — otherwise there is no rate ("not available",
  never guessed);
* ECB currencies convert through the euro on the same ECB day (``to / from``);
* NPR converts with Nepal Rastra Bank's middle rate for the other currency, or, when NRB does not
  quote it, through USD (NRB for NPR↔USD, then the ECB for USD↔the other currency);
* exact decimals with 34 significant digits; nothing is rounded here (display only).
"""

from __future__ import annotations

import bisect
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domains.fx.models import FxRate
from app.domains.fx.sources import EcbSource, FxSource, NrbSource, PublishedRate
from app.providers.base.errors import ProviderError
from app.providers.http.client import SafeHttpClient
from app.runtime import Runtime, outbound_policy

logger = logging.getLogger("advegax.fx")

EUR, NPR, USD = "EUR", "NPR", "USD"
PRECISION = 34


# ------------------------------------------------------------------ refresh
def sources(rt: Runtime) -> Sequence[FxSource]:
    """The configured sources (tests put recorded ones in ``rt.extras["fx_sources"]``)."""
    injected = rt.extras.get("fx_sources")
    if injected is not None:
        return injected  # type: ignore[return-value]
    policy = outbound_policy(rt.settings)
    return (EcbSource(lambda: SafeHttpClient(policy)), NrbSource(lambda: SafeHttpClient(policy)))


def refresh_rates(rt: Runtime) -> int:
    """Read and store the rates each source has published since it was last read. Returns
    how many rows were written. Does nothing unless ``FX_ENABLED``."""
    if not rt.settings.FX_ENABLED:
        return 0
    today = rt.clock.now().date()
    written = 0
    for source in sources(rt):
        with rt.db.transaction(system=True) as session:
            newest = session.execute(
                select(func.max(FxRate.rate_date)).where(FxRate.source == source.code)
            ).scalar_one()
        first = (
            today - rt.settings.FX_HISTORY_WINDOW
            if newest is None
            else newest - rt.settings.FX_REFRESH_DAYS
        )
        try:
            rows = _fetch(rt, source, first, today)
        except ProviderError as exc:
            logger.warning("fx_source_failed", extra={"source": source.code, "error": exc.code})
            continue
        written += store(rt, rows)
        logger.info("fx_rates_stored", extra={"source": source.code, "rows": len(rows)})
    return written


def _fetch(rt: Runtime, source: FxSource, first: date, last: date) -> list[PublishedRate]:
    """In slices of ``FX_FETCH_SLICE`` so no answer grows beyond the response size limit."""
    found: list[PublishedRate] = []
    start = first
    span = rt.settings.FX_FETCH_SLICE.days
    while start <= last:
        end = min(last, date.fromordinal(start.toordinal() + span - 1))
        found += source.fetch(start, end)
        start = date.fromordinal(end.toordinal() + 1)
    return found


def store(rt: Runtime, rows: Iterable[PublishedRate]) -> int:
    values = [
        {
            "source": r.source,
            "base": r.base,
            "quote": r.quote,
            "rate_date": r.rate_date,
            "rate": r.rate,
            "unit": r.unit,
            "fetched_at": rt.clock.now(),
        }
        for r in rows
    ]
    if not values:
        return 0
    with rt.db.transaction(system=True) as session:
        stmt = insert(FxRate).values(values)
        session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_fx_rates_source_base_quote_rate_date",
                set_={
                    "rate": stmt.excluded.rate,
                    "unit": stmt.excluded.unit,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
        )
    return len(values)


# ------------------------------------------------------------------ conversion
@dataclass(frozen=True)
class Rate:
    """1 unit of ``from`` is worth ``value`` units of ``to``, published on ``rate_date``."""

    value: Decimal
    rate_date: date
    sources: tuple[str, ...]


class _Daily:
    """One source's rates by day: ``per_unit[day][currency]``, days sorted for look-back."""

    def __init__(self) -> None:
        self.per_unit: dict[date, dict[str, Decimal]] = {}
        self.days: list[date] = []

    def add(self, day: date, currency: str, value: Decimal) -> None:
        self.per_unit.setdefault(day, {})[currency] = value

    def finish(self) -> None:
        self.days = sorted(self.per_unit)

    def latest(self, day: date, oldest: date, *currencies: str) -> date | None:
        """The newest day ≤ ``day`` (and ≥ ``oldest``) quoting every currency asked for."""
        i = bisect.bisect_right(self.days, day) - 1
        while i >= 0 and self.days[i] >= oldest:
            rates = self.per_unit[self.days[i]]
            if all(c in rates for c in currencies):
                return self.days[i]
            i -= 1
        return None


class FxTable:
    """The rates needed for a period, loaded once; conversions happen in memory."""

    def __init__(self, rows: Iterable[Any], max_stale: timedelta) -> None:
        self._max_stale = max_stale
        self._ecb, self._nrb = _Daily(), _Daily()
        with localcontext() as ctx:
            ctx.prec = PRECISION
            for r in rows:
                if r.source == "ecb" and r.base == EUR:
                    self._ecb.add(r.rate_date, r.quote, Decimal(r.rate) / r.unit)
                elif r.source == "nrb" and r.quote == NPR:
                    self._nrb.add(r.rate_date, r.base, Decimal(r.rate) / r.unit)
        self._ecb.finish()
        self._nrb.finish()

    @classmethod
    def load(cls, session: Session, first: date, last: date, max_stale: timedelta) -> FxTable:
        rows = session.execute(
            select(
                FxRate.source, FxRate.base, FxRate.quote, FxRate.rate_date, FxRate.rate, FxRate.unit
            ).where(FxRate.rate_date >= first - max_stale, FxRate.rate_date <= last)
        ).all()
        return cls(rows, max_stale)

    def rate(self, source: str, target: str, day: date) -> Rate | None:
        if source == target:
            return Rate(Decimal(1), day, ())
        with localcontext() as ctx:
            ctx.prec = PRECISION
            if NPR in (source, target):
                return self._npr(source, target, day)
            return self._ecb_rate(source, target, day)

    def convert(self, amount: Decimal, source: str, target: str, day: date) -> Decimal | None:
        found = self.rate(source, target, day)
        if found is None:
            return None
        with localcontext() as ctx:
            ctx.prec = PRECISION
            return amount * found.value

    def _ecb_rate(self, source: str, target: str, day: date) -> Rate | None:
        needed = [c for c in (source, target) if c != EUR]
        when = self._ecb.latest(day, day - self._max_stale, *needed)
        if when is None:
            return None
        rates = self._ecb.per_unit[when]
        per_eur_source = Decimal(1) if source == EUR else rates[source]
        per_eur_target = Decimal(1) if target == EUR else rates[target]
        return Rate(per_eur_target / per_eur_source, when, ("ecb",))

    def _npr(self, source: str, target: str, day: date) -> Rate | None:
        other = target if source == NPR else source
        oldest = day - self._max_stale
        direct = self._nrb.latest(day, oldest, other)
        if direct is not None:
            npr_per_other = self._nrb.per_unit[direct][other]
            value = npr_per_other if source == other else 1 / npr_per_other
            return Rate(value, direct, ("nrb",))
        via = self._nrb.latest(day, oldest, USD)
        if via is None:
            return None
        through = (
            self._ecb_rate(USD, other, day) if source == NPR else self._ecb_rate(other, USD, day)
        )
        if through is None:
            return None
        npr_per_usd = self._nrb.per_unit[via][USD]
        # NPR → USD → other, or other → USD → NPR
        value = through.value / npr_per_usd if source == NPR else through.value * npr_per_usd
        return Rate(value, min(via, through.rate_date), ("nrb", "ecb"))
