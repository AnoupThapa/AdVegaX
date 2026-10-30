"""Where exchange rates come from (Phase 6, task 6-03, PHASE_06_PLAN §4.1, Q-6-3).

Two public, official, free sources, read over the SSRF-safe client with **GET only** to fixed
addresses (no credentials, no personal or tenant data, no redirects followed):

* **European Central Bank** — euro reference rates for about 30 currencies, each TARGET working
  day, through the ECB Data Portal (SDMX ``EXR`` dataflow, series ``D.<CUR>.EUR.SP00.A``, CSV).
  Read by the column names in the header, so a change in column order does not matter.
* **Nepal Rastra Bank** — NPR buy and sell rates for about 20 currencies, daily; some per 10 or
  100 units. AdVegaX stores the middle rate ((buy + sell) / 2) with NRB's unit.

Shapes as documented (checked 2026-10-20; **to confirm live, Step 0 / 6-01**). Anything that
cannot be read is skipped and counted, never guessed; an answer that is not what was asked for
stops the read for that source only.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import urlencode

from app.providers.base.errors import InvalidRequestError, RetryableError
from app.providers.http.client import SafeHttpClient, SafeResponse

logger = logging.getLogger("advegax.fx.sources")

ECB_HOST = "data-api.ecb.europa.eu"
ECB_PATH = "/service/data/EXR/D..EUR.SP00.A"  # every currency against the euro, daily
NRB_HOST = "www.nrb.org.np"
NRB_PATH = "/api/forex/v1/rates"
NRB_PAGE_SIZE = 100
MAX_PAGES = 50
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_NUMBER = re.compile(r"^[0-9]{1,12}(\.[0-9]{1,12})?$")

HttpFactory = Callable[[], SafeHttpClient]


class FxSourceError(RetryableError):
    code = "fx_source_unavailable"


class FxAnswerError(InvalidRequestError):
    """The source answered with something that is not the documented format."""

    code = "fx_unexpected_answer"


@dataclass(frozen=True)
class PublishedRate:
    """``unit`` units of ``base`` are worth ``rate`` units of ``quote``, as published."""

    source: str
    base: str
    quote: str
    rate_date: date
    rate: Decimal
    unit: int = 1


class FxSource(Protocol):
    code: str

    def fetch(self, first: date, last: date) -> list[PublishedRate]: ...


def _decimal(value: Any) -> Decimal | None:
    if not isinstance(value, str) or not _NUMBER.fullmatch(value.strip()):
        return None
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        return None
    return number if number > 0 else None


def _units(value: Any) -> int | None:
    """NRB's quotation unit (1, 10, 100 …), given as a number or a string of digits."""
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 100_000:
        return None
    return value


def _day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _get(http_factory: HttpFactory, host: str, path: str, params: dict[str, str]) -> SafeResponse:
    """The only way out: GET to one of the two fixed addresses."""
    if (host, path) not in ((ECB_HOST, ECB_PATH), (NRB_HOST, NRB_PATH)):
        raise ValueError(f"refused exchange-rate address: {host}{path}")
    client = http_factory()
    try:
        response = client.request(
            "GET",
            f"https://{host}{path}?{urlencode(params)}",
            headers={"Accept": "text/csv" if host == ECB_HOST else "application/json"},
            follow_redirects=False,
        )
    finally:
        client.close()
    if response.status_code >= 500 or response.status_code == 429:
        raise FxSourceError()
    return response


class EcbSource:
    code = "ecb"

    def __init__(self, http_factory: HttpFactory) -> None:
        self._http = http_factory

    def fetch(self, first: date, last: date) -> list[PublishedRate]:
        response = _get(
            self._http,
            ECB_HOST,
            ECB_PATH,
            {
                "startPeriod": first.isoformat(),
                "endPeriod": last.isoformat(),
                "format": "csvdata",
                "detail": "dataonly",
            },
        )
        if response.status_code == 404:  # the ECB answers 404 when a period has no rates
            return []
        if response.status_code != 200:
            raise FxAnswerError()
        try:
            text = response.content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise FxAnswerError() from None
        reader = csv.DictReader(io.StringIO(text))
        needed = {"CURRENCY", "CURRENCY_DENOM", "TIME_PERIOD", "OBS_VALUE"}
        if reader.fieldnames is None or not needed <= set(reader.fieldnames):
            raise FxAnswerError()
        found, skipped = [], 0
        for row in reader:
            quote, base = row.get("CURRENCY") or "", row.get("CURRENCY_DENOM") or ""
            day, rate = _day(row.get("TIME_PERIOD")), _decimal(row.get("OBS_VALUE"))
            ok = base == "EUR" and _CURRENCY.fullmatch(quote) and quote != "EUR"
            if not ok or day is None or rate is None or not first <= day <= last:
                skipped += 1
                continue
            found.append(PublishedRate(self.code, "EUR", quote, day, rate))
        if skipped:
            logger.warning("fx_rows_skipped", extra={"source": self.code, "count": skipped})
        return found


class NrbSource:
    code = "nrb"

    def __init__(self, http_factory: HttpFactory) -> None:
        self._http = http_factory

    def fetch(self, first: date, last: date) -> list[PublishedRate]:
        found: list[PublishedRate] = []
        skipped = 0
        for page in range(1, MAX_PAGES + 1):
            response = _get(
                self._http,
                NRB_HOST,
                NRB_PATH,
                {
                    "page": str(page),
                    "per_page": str(NRB_PAGE_SIZE),
                    "from": first.isoformat(),
                    "to": last.isoformat(),
                },
            )
            if response.status_code != 200:
                raise FxAnswerError()
            try:
                body = json.loads(response.content)
            except (ValueError, UnicodeDecodeError):
                raise FxAnswerError() from None
            data = body.get("data") if isinstance(body, dict) else None
            payload = data.get("payload") if isinstance(data, dict) else None
            if not isinstance(payload, list):
                raise FxAnswerError()
            for day_entry in payload:
                rates, day_skipped = self._day_rates(day_entry, first, last)
                found += rates
                skipped += day_skipped
            pagination = body.get("pagination") if isinstance(body, dict) else None
            pages = pagination.get("pages") if isinstance(pagination, dict) else None
            if not isinstance(pages, int) or isinstance(pages, bool) or page >= pages:
                break
        else:
            raise FxAnswerError()  # still "more pages" after MAX_PAGES: stop rather than loop
        if skipped:
            logger.warning("fx_rows_skipped", extra={"source": self.code, "count": skipped})
        return found

    def _day_rates(self, entry: Any, first: date, last: date) -> tuple[list[PublishedRate], int]:
        day = _day(entry.get("date")) if isinstance(entry, dict) else None
        rates = entry.get("rates") if isinstance(entry, dict) else None
        if day is None or not isinstance(rates, list) or not first <= day <= last:
            return [], 1
        found, skipped = [], 0
        for item in rates:
            currency = item.get("currency") if isinstance(item, dict) else None
            code = currency.get("iso3") if isinstance(currency, dict) else None
            unit = currency.get("unit") if isinstance(currency, dict) else None
            buy = _decimal(item.get("buy")) if isinstance(item, dict) else None
            sell = _decimal(item.get("sell")) if isinstance(item, dict) else None
            units = _units(unit)
            ok = isinstance(code, str) and _CURRENCY.fullmatch(code) and code != "NPR"
            if not ok or units is None or buy is None or sell is None:
                skipped += 1
                continue
            middle = (buy + sell) / 2
            found.append(PublishedRate(self.code, str(code), "NPR", day, middle, units))
        return found, skipped
