"""What the copywriter sees (Phase 9, task 9-04, PLAN Q-9-2; A12).

From a strategy marked **ready**:

* ``brief`` — the plan as approved: objective, positioning, angles, and per platform its
  campaign type and audience (no budget amounts — copy never needs them);
* ``facts`` — the product's catalogue **prices** in the store's currency (the only prices the
  copy may state; checked again by ``policy.py``), the store currency and platform;
* ``store_text`` — the product's own words (title, type, vendor, variant names), cleaned and
  sealed as **untrusted** exactly as in Phase 8.

The brief is the merchant's approved (and possibly edited) text, so it too is sent as data in a
sealed block. Nothing else: no customers, orders, accounts, campaign names, IDs or secrets.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, StrategyNotReady
from app.domains.ai.models import CampaignStrategy
from app.domains.commerce.models import Product, ProductVariant, Store
from app.domains.finance.definitions import for_display
from app.domains.strategy.context import MAX_SHORT, MAX_TITLE, MAX_VARIANTS, clean, delimited

BRIEF_OPEN, BRIEF_CLOSE = "<brief>", "</brief>"
CONTEXT_VERSION = "creative-context-v1"


def sealed_brief(brief: dict[str, Any]) -> str:
    body = json.dumps(brief, ensure_ascii=False, sort_keys=True)
    body = body.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"{BRIEF_OPEN}\n{body}\n{BRIEF_CLOSE}"


@dataclass
class CreativeContext:
    organization_id: uuid.UUID
    strategy_id: uuid.UUID
    product_id: uuid.UUID
    platforms: list[str]
    prices: list[Decimal]
    currency: str
    brief: dict[str, Any]
    facts: dict[str, Any]
    store_text: dict[str, Any]

    def snapshot(self) -> dict[str, Any]:
        return {
            "context_version": CONTEXT_VERSION,
            "brief": self.brief,
            "facts": self.facts,
            "store_text": self.store_text,
        }

    def prompt_parts(self) -> dict[str, str]:
        return {
            "facts": json.dumps(self.facts, indent=1, sort_keys=True),
            "brief": sealed_brief(self.brief),
            "store_text": delimited(self.store_text),
        }


def _text(value: Any, limit: int) -> str | None:
    return clean(value, limit) if isinstance(value, str) else None


def build_creative_context(
    session: Session, *, organization_id: uuid.UUID, strategy_id: uuid.UUID
) -> CreativeContext:
    row = session.execute(
        select(CampaignStrategy).where(
            CampaignStrategy.organization_id == organization_id,
            CampaignStrategy.id == strategy_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound()
    if row.status != "ready":
        raise StrategyNotReady()
    found = session.execute(
        select(Product, Store.currency, Store.provider)
        .join(
            Store,
            (Store.id == Product.store_id) & (Store.organization_id == Product.organization_id),
        )
        .where(Product.organization_id == organization_id, Product.id == row.product_id)
    ).first()
    if found is None:
        raise NotFound()
    product, currency, store_platform = found
    variants = list(
        session.execute(
            select(ProductVariant).where(
                ProductVariant.organization_id == organization_id,
                ProductVariant.product_id == product.id,
                ProductVariant.deleted.is_(False),
            )
        ).scalars()
    )
    prices = sorted({v.price for v in variants if v.price is not None})
    plan = row.strategy
    platforms = [p.get("platform") for p in plan.get("platforms", [])]
    brief = {
        "objective": plan.get("objective"),
        "positioning": _text(plan.get("positioning"), 400),
        "angles": [_text(a.get("angle"), 200) for a in plan.get("angles", [])],
        "platforms": [
            {
                "platform": p.get("platform"),
                "campaign_type": p.get("campaign_type"),
                "audience": _text(p.get("audience"), 400),
            }
            for p in plan.get("platforms", [])
        ],
    }
    facts = {
        "store_currency": currency,
        "store_platform": store_platform,
        "catalogue_prices": [str(for_display(p, currency)) for p in prices],
        "language": "English",
    }
    store_text = {
        "title": clean(product.title, MAX_TITLE),
        "product_type": clean(product.product_type, MAX_SHORT),
        "vendor": clean(product.vendor, MAX_SHORT),
        "variant_names": [
            t for t in (clean(v.title, MAX_SHORT) for v in variants[:MAX_VARIANTS]) if t
        ],
    }
    return CreativeContext(
        organization_id=organization_id,
        strategy_id=row.id,
        product_id=product.id,
        platforms=[p for p in platforms if isinstance(p, str)],
        prices=list(prices),
        currency=currency,
        brief=brief,
        facts=facts,
        store_text=store_text,
    )
