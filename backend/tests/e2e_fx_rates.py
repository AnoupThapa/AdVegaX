"""Store recorded exchange rates for the browser end-to-end tests (task 6-09).

    uv run python -m tests.e2e_fx_rates

Runs the **real** daily rate task (``refresh_rates``) against the recorded-format ECB and Nepal
Rastra Bank answers of ``tests.fx_sim``, behind the real ``SafeHttpClient``: weekday rates for
the last 60 days (no weekends, as the ECB publishes), so converted figures and the "last
published rate" rule show in the browser. Nothing leaves the machine: CI never calls either
bank. Prints ``{"rows": n}`` as JSON. Refuses to run in a deployed environment; this module is
excluded from the Docker image.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal

from app.core.settings import get_settings
from app.domains.fx.service import refresh_rates
from app.runtime import build_runtime

from tests.fx_sim import FxSim

ECB = {"AUD": "1.6512", "NZD": "1.8015", "USD": "1.0856"}


def main() -> int:
    settings = get_settings()
    if settings.is_deployed:
        print(json.dumps({"error": "refusing to run in a deployed environment"}), file=sys.stderr)
        return 1
    runtime = build_runtime(settings.model_copy(update={"FX_ENABLED": True}))
    try:
        sim = FxSim(nrb_per_page=100)
        today = runtime.clock.now().date()
        for back in range(60):
            day = date.fromordinal(today.toordinal() - back)
            if day.weekday() >= 5:
                continue  # the ECB publishes on working days
            for currency, rate in ECB.items():
                sim.ecb[(day, currency)] = Decimal(rate)
            sim.nrb[(day, "USD")] = ("150.10", "150.70", 1)
        runtime.extras["fx_sources"] = sim.sources()
        print(json.dumps({"rows": refresh_rates(runtime)}))
        return 0
    finally:
        runtime.close()


if __name__ == "__main__":
    sys.exit(main())
