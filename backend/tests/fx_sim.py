"""Recorded-format exchange-rate sources for tests (Phase 6, 6-03).

Answers like the ECB Data Portal (SDMX ``csvdata``, ``detail=dataonly``) and Nepal Rastra Bank's
rate API (JSON with ``data.payload`` and ``pagination``), as documented (checked 2026-10-20;
Step 0 confirms them live). Served behind the real ``SafeHttpClient`` with a fake resolver and
``httpx.MockTransport``. No network — CI never calls either bank.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs

import httpx
from app.domains.fx.sources import EcbSource, NrbSource
from app.providers.http.client import OutboundPolicy, SafeHttpClient

PUBLIC_IP = "185.199.108.153"
POLICY = OutboundPolicy(
    connect_timeout=1, read_timeout=1, max_response_bytes=5_000_000, max_redirects=0
)
ECB_HEADER = "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE"


@dataclass
class FxSim:
    # ECB: (day, currency) → units of currency per 1 EUR.
    ecb: dict[tuple[date, str], Decimal] = field(default_factory=dict)
    # NRB: (day, currency) → (buy, sell, unit) in NPR per ``unit`` of currency.
    nrb: dict[tuple[date, str], tuple[str, str, int]] = field(default_factory=dict)
    nrb_per_page: int = 3  # small, so tests page
    fail: dict[str, int] = field(default_factory=dict)  # host → HTTP status for every call
    requests: list[httpx.Request] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.headers.get("host", "")
        if request.method != "GET":
            return httpx.Response(405)
        if host in self.fail:
            return httpx.Response(self.fail[host], text="error")
        query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        if host == "data-api.ecb.europa.eu":
            return self._ecb(request.url.path, query)
        if host == "www.nrb.org.np":
            return self._nrb(query)
        return httpx.Response(404)

    def _ecb(self, path: str, query: dict[str, str]) -> httpx.Response:
        if path != "/service/data/EXR/D..EUR.SP00.A" or query.get("format") != "csvdata":
            return httpx.Response(400, text="bad request")
        first, last = (
            date.fromisoformat(query["startPeriod"]),
            date.fromisoformat(query["endPeriod"]),
        )
        rows = [
            f"EXR.D.{cur}.EUR.SP00.A,D,{cur},EUR,SP00,A,{day.isoformat()},{rate}"
            for (day, cur), rate in sorted(self.ecb.items())
            if first <= day <= last
        ]
        if not rows:
            return httpx.Response(404, text="No results found.")
        return httpx.Response(200, text="\n".join([ECB_HEADER, *rows]) + "\n")

    def _nrb(self, query: dict[str, str]) -> httpx.Response:
        first, last = date.fromisoformat(query["from"]), date.fromisoformat(query["to"])
        days = sorted({d for d, _ in self.nrb if first <= d <= last})
        size = min(int(query.get("per_page", "100")), self.nrb_per_page)
        page = int(query.get("page", "1"))
        shown = days[(page - 1) * size : page * size]
        payload = [
            {
                "date": d.isoformat(),
                "published_on": f"{d.isoformat()} 00:00:05",
                "rates": [
                    {
                        "currency": {"iso3": cur, "name": cur, "unit": unit},
                        "buy": buy,
                        "sell": sell,
                    }
                    for (day, cur), (buy, sell, unit) in sorted(self.nrb.items())
                    if day == d
                ],
            }
            for d in shown
        ]
        pages = max(1, -(-len(days) // size))
        return httpx.Response(
            200,
            json={
                "status": {"code": 200},
                "data": {"payload": payload},
                "pagination": {"page": page, "pages": pages, "per_page": size, "total": len(days)},
            },
        )

    def http_factory(self) -> SafeHttpClient:
        return SafeHttpClient(
            POLICY,
            resolver=lambda host, port: [PUBLIC_IP],
            transport=httpx.MockTransport(self.handler),
        )

    def sources(self) -> tuple[EcbSource, NrbSource]:
        return EcbSource(self.http_factory), NrbSource(self.http_factory)

    def calls(self, host: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.headers.get("host") == host]
