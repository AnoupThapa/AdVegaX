"""Create AdVegaX's prices in Stripe (Phase 13, task 13-03, PHASE_13_PLAN §2A).

Run once per Stripe account (test mode first)::

    uv run python -m app.domains.billing.setup

It reads the plans in ``billing/plans.py`` and creates, for each plan and interval, a product
and a price with the lookup key ``advegax_<plan>_<interval>`` — only those not already there,
so running it again changes nothing. Prices include GST (``tax_behavior=inclusive``). The
Stripe key comes from the local settings file and is never printed.
"""

from __future__ import annotations

import sys

from app.core.errors import BillingUnavailable
from app.core.settings import get_settings
from app.domains.billing.provider import BillingError
from app.domains.billing.service import missing_prices, provider_for
from app.runtime import Runtime, build_runtime


def run(rt: Runtime) -> list[str]:
    """Create the missing prices; returns their lookup keys."""
    provider = provider_for(rt)
    created = []
    for price in missing_prices(rt, provider):
        provider.create_price(price)
        created.append(price.lookup_key)
    return created


def main() -> int:  # pragma: no cover - a command for people, exercised through ``run``
    rt = build_runtime(get_settings())
    try:
        created = run(rt)
    except BillingUnavailable:
        print("Billing is off or STRIPE_SECRET_KEY is not set in the local settings file.")
        return 1
    except BillingError as exc:
        print(f"Stripe refused or could not be reached ({exc.code}).")
        return 1
    finally:
        rt.close()
    if created:
        print("Created: " + ", ".join(created))
    else:
        print("Every price already exists; nothing changed.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
