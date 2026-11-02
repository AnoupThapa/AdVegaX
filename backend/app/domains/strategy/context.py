"""What the campaign planner shows the model (Phase 8, task 8-03, PLAN Q-8-2, §8; A12).

The context for one product is built **only from AdVegaX's own deterministic figures** — the
Phase 6 product, business and platform figures and the Phase 7 funnel with its findings — for
the product's store and what is assigned to it, over the last ``PLANNER_CONTEXT_DAYS`` complete
days (shortened to what every source has fully read, so nothing is "not synced" only because a
source is new):

* ``figures``: a flat map of **evidence keys** → label, unit, value and availability. The model
  must cite these keys as its evidence (8-04 checks they exist); a figure AdVegaX does not have
  stays unknown with its reason — **never 0**.
* ``facts``: the product's status and store platform, the connected ad platforms (by code
  only), the reporting currency and the period.
* ``findings``: the funnel's drop-offs (Q-7-7) for the whole business and each ad platform.
* ``store_text``: the product's own words (title, type, vendor, variant names) — **untrusted**:
  shortened, stripped of control characters and sent inside a delimited block whose markers
  cannot appear in the text, so instructions hidden in a title are only data.

Never in the context: customers, orders, emails, addresses, phone numbers, tokens or secrets,
and no free text from ad accounts, campaigns or analytics channels (their names are the
merchant's or a platform's words; only platform codes are used). A static test checks the
imports and the field names of this module.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.settings import Settings
from app.domains.commerce.models import Product, ProductCostHistory, ProductVariant
from app.domains.funnel.engine import load_funnel, whole
from app.domains.funnel.findings import find_drop_offs, rules_from
from app.domains.funnel.registry import STAGES
from app.domains.fx.service import FxTable
from app.domains.metrics.campaigns import products
from app.domains.metrics.channels import platforms
from app.domains.metrics.engine import (
    AVAILABLE,
    UNAVAILABLE,
    Figure,
    Scope,
    compute,
    load_inputs,
    load_scope,
    missing,
)
from app.domains.metrics.registry import BY_KEY, TABLES, Metric
from app.domains.organizations.models import Organization

CONTEXT_VERSION = "planner-context-v1"
STORE_TEXT_OPEN = "<store_text>"
STORE_TEXT_CLOSE = "</store_text>"
MAX_TITLE = 200
MAX_SHORT = 80
MAX_VARIANTS = 20
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]")
_SPACES = re.compile(r"\s+")

# The organization-level figures the planner shows (the Phase 6 registry, by key).
BUSINESS_KEYS = (
    "net_sales",
    "orders",
    "gross_profit",
    "gross_margin",
    "ad_spend",
    "profit_after_ad_spend",
    "blended_roas",
    "sessions",
    "store_conversion_rate",
)
PLATFORM_KEYS = (
    "spend",
    "clicks",
    "impressions",
    "conversions",
    "conversion_value",
    "platform_roas",
    "cost_per_click",
    "cost_per_conversion",
)
_PLATFORM = {m.key: m for m in TABLES["channels"]}
_PRODUCT = {m.key: m for m in TABLES["products"]}
_STAGE_LABELS = {s.key: s.label for s in STAGES}


@dataclass(frozen=True)
class Evidence:
    key: str
    label: str
    unit: str  # money | count | ratio | multiple | decimal
    value: Decimal | None
    availability: str
    reason: str | None
    currency: str | None = None  # money only: the reporting currency

    def out(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "unit": self.unit,
            "value": None if self.value is None else str(self.value),
            "availability": self.availability,
            "reason": self.reason,
            **({"currency": self.currency} if self.currency else {}),
        }


@dataclass
class PlanningContext:
    organization_id: uuid.UUID
    product_id: uuid.UUID
    store_id: uuid.UUID
    currency: str
    first: date
    last: date
    recent_first: date
    facts: dict[str, Any]
    figures: dict[str, Evidence] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    store_text: dict[str, Any] = field(default_factory=dict)

    @property
    def platforms(self) -> list[str]:
        return list(self.facts["connected_ad_platforms"])

    def data(self) -> dict[str, Any]:
        """The figures, facts and findings — what the model may reason over."""
        return {
            "context_version": CONTEXT_VERSION,
            "facts": self.facts,
            "figures": {k: e.out() for k, e in sorted(self.figures.items())},
            "findings": self.findings,
        }

    def snapshot(self) -> dict[str, Any]:
        """What ``ai_runs.context_snapshot`` records: everything sent, as sent."""
        return {**self.data(), "store_text": self.store_text}

    def prompt_parts(self) -> dict[str, str]:
        """The two blocks a planner prompt is filled with (8-04)."""
        return {
            "figures": json.dumps(self.data(), indent=1, sort_keys=True),
            "store_text": delimited(self.store_text),
        }


# ------------------------------------------------------------------ untrusted text
def clean(text: str | None, limit: int) -> str | None:
    """Store text, made safe to show the model as data: no control or invisible characters,
    one line, at most ``limit`` characters. None stays None."""
    if text is None:
        return None
    flat = _SPACES.sub(" ", _CONTROL.sub(" ", text)).strip()
    return flat[:limit] or None


def delimited(store_text: dict[str, Any]) -> str:
    """The store text as JSON inside markers it can never close: ``<`` and ``>`` are escaped,
    so a title containing ``</store_text>`` is still inside the block."""
    body = json.dumps(store_text, ensure_ascii=False, sort_keys=True)
    body = body.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"{STORE_TEXT_OPEN}\n{body}\n{STORE_TEXT_CLOSE}"


# ------------------------------------------------------------------ figures
def _evidence(
    key: str, metric: Metric | None, label: str, unit: str, f: Figure, cur: str
) -> Evidence:
    unit = metric.unit if metric else unit
    return Evidence(
        key=key,
        label=metric.label if metric else label,
        unit=unit,
        value=f.value if f.ok else None,
        availability=f.availability if not f.ok else AVAILABLE,
        reason=None if f.ok else f.reason,
        currency=cur if unit == "money" else None,
    )


def _shift(day: date, days: int) -> date:
    return date.fromordinal(day.toordinal() + days)


def _window(scope: Scope, last: date, days: int) -> date:
    """The first day: ``days`` back from ``last``, but not before every source in scope has
    fully read its history (a source that has not finished stays "not synced")."""
    first = _shift(last, -(days - 1))
    starts = [s.synced_from for s in scope.sources]
    if starts and all(s is not None for s in starts):
        first = max(first, *(s for s in starts if s is not None))
    return min(first, last)


def _product_figures(
    session: Session,
    scope: Scope,
    first: date,
    last: date,
    fx: FxTable,
    product_id: uuid.UUID,
    prefix: str,
) -> dict[str, Evidence]:
    listed, why, _ = products(session, scope, first, last, fx)
    found = next((p for p in listed if p.product_id == product_id), None)
    keys = ("units", "net_sales", "product_cost", "gross_profit", "gross_margin")
    out: dict[str, Evidence] = {}
    for key in keys:
        if why is not None:
            figure = why
        elif found is None:  # every day was read and the product sold nothing: real zeros
            figure = (
                missing(UNAVAILABLE, "no_net_sales")
                if key == "gross_margin"
                else Figure(Decimal(0))
            )
        else:
            figure = found.figures[key]
        name = f"{prefix}{key}"
        out[name] = _evidence(name, _PRODUCT[key], "", "", figure, scope.currency)
    return out


def _catalogue_figures(
    session: Session, product: Product, scope: Scope, fx: FxTable, day: date, now: datetime
) -> tuple[dict[str, Evidence], dict[str, Any]]:
    """Price, unit cost and stock of the product's variants (today's catalogue)."""
    variants = list(
        session.execute(
            select(ProductVariant).where(
                ProductVariant.organization_id == product.organization_id,
                ProductVariant.product_id == product.id,
                ProductVariant.deleted.is_(False),
            )
        ).scalars()
    )
    store_currency = next(s.currency for s in scope.stores if s.id == product.store_id)
    costs: dict[uuid.UUID, ProductCostHistory] = {}
    if variants:
        for row in session.execute(
            select(ProductCostHistory)
            .where(
                ProductCostHistory.organization_id == product.organization_id,
                ProductCostHistory.variant_id.in_([v.id for v in variants]),
                ProductCostHistory.effective_from <= now,
            )
            .order_by(ProductCostHistory.effective_from)
        ).scalars():
            costs[row.variant_id] = row  # the latest one wins

    def money(amount: Decimal | None, currency: str, reason: str) -> Figure:
        if amount is None:
            return missing(UNAVAILABLE, reason)
        converted = fx.convert(amount, currency, scope.currency, day)
        return (
            Figure(converted) if converted is not None else missing(UNAVAILABLE, "no_exchange_rate")
        )

    prices = [money(v.price, store_currency, "no_price") for v in variants]
    unit_costs = [
        money(
            costs[v.id].unit_cost if v.id in costs else None,
            costs[v.id].currency if v.id in costs else store_currency,
            "missing_product_costs",
        )
        for v in variants
    ]
    cur = scope.currency

    def bound(values: list[Figure], pick: Any, reason: str) -> Figure:
        if not values:
            return missing(UNAVAILABLE, "no_variants")
        bad = next((f for f in values if not f.ok), None)
        if bad is not None:
            return Figure(None, bad.availability, bad.reason or reason)
        return Figure(pick(f.value for f in values))

    tracked = [v for v in variants if v.inventory_tracked]
    stock = (
        Figure(Decimal(sum(max(v.inventory_available or 0, 0) for v in tracked)))
        if tracked and all(v.inventory_available is not None for v in tracked)
        else missing(UNAVAILABLE, "stock_not_tracked" if not tracked else "stock_not_read")
    )
    out_of_stock = (
        Figure(Decimal(sum(1 for v in tracked if (v.inventory_available or 0) <= 0)))
        if stock.ok
        else stock
    )
    figures = {
        "product.price_min": ("Lowest variant price", "money", bound(prices, min, "no_price")),
        "product.price_max": ("Highest variant price", "money", bound(prices, max, "no_price")),
        "product.unit_cost_min": (
            "Lowest variant unit cost",
            "money",
            bound(unit_costs, min, "missing_product_costs"),
        ),
        "product.unit_cost_max": (
            "Highest variant unit cost",
            "money",
            bound(unit_costs, max, "missing_product_costs"),
        ),
        "product.stock_available": ("Units in stock (tracked variants)", "count", stock),
        "product.variants_out_of_stock": ("Tracked variants out of stock", "count", out_of_stock),
    }
    evidence = {
        k: _evidence(k, None, label, unit, f, cur) for k, (label, unit, f) in figures.items()
    }
    facts = {
        "variants": len(variants),
        "stock_tracked": bool(tracked) and len(tracked) == len(variants),
    }
    return evidence, {"variant_titles": [v.title for v in variants[:MAX_VARIANTS]], **facts}


def build_context(
    session: Session,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
    product_id: uuid.UUID,
    now: datetime,
) -> PlanningContext:
    """The planning context of one of the organization's products (``NotFound`` otherwise).
    Whether the product can be planned at all (status, stock) is decided by 8-04's rules."""
    org = session.get(Organization, organization_id)
    product = session.execute(
        select(Product).where(Product.organization_id == organization_id, Product.id == product_id)
    ).scalar_one_or_none()
    if org is None or product is None:
        raise NotFound()
    scope = load_scope(
        session,
        organization_id=organization_id,
        currency=org.default_currency,
        timezone=org.default_timezone,
        now=now,
        store_id=product.store_id,
    )
    today = now.astimezone(ZoneInfo(org.default_timezone)).date()
    last = _shift(today, -1)  # complete days only
    first = _window(scope, last, settings.PLANNER_CONTEXT_DAYS)
    recent_first = max(first, _shift(last, -(settings.PLANNER_RECENT_DAYS - 1)))
    rules = rules_from(settings)
    span = last.toordinal() - first.toordinal() + 1
    wide_first = _shift(first, -max(span, rules.baseline_days))
    fx = FxTable.load(session, wide_first, last, settings.FX_MAX_STALE_DAYS)
    cur = scope.currency

    figures: dict[str, Evidence] = {}
    figures.update(_product_figures(session, scope, first, last, fx, product.id, "product."))
    figures.update(
        _product_figures(session, scope, recent_first, last, fx, product.id, "product.recent_")
    )
    catalogue, text_parts = _catalogue_figures(session, product, scope, fx, last, now)
    figures.update(catalogue)

    inputs = load_inputs(session, scope, first, last, fx)
    business = compute(scope, inputs.period())
    for key in BUSINESS_KEYS:
        if key in business:
            name = f"business.{key}"
            figures[name] = _evidence(name, BY_KEY.get(key), key, "decimal", business[key], cur)

    connected: list[str] = []
    for found in platforms(session, scope, first, last, fx):
        connected.append(found.provider)
        for key in PLATFORM_KEYS:
            name = f"platform.{found.provider}.{key}"
            metric = _PLATFORM.get(key)
            figures[name] = _evidence(name, metric, key, "decimal", found.figures[key], cur)

    funnel = load_funnel(session, scope, load_inputs(session, scope, wide_first, last, fx))
    stages, steps = whole(scope, funnel.period(first, last))
    for key, figure in stages.items():
        name = f"funnel.{key}"
        figures[name] = _evidence(name, None, _STAGE_LABELS[key], "count", figure, cur)
    for step in steps:
        if step.rate is None:
            continue  # different sources: no rate (Q-7-2)
        name = f"funnel.rate.{step.step.from_stage}.{step.step.to_stage}"
        label = f"{_STAGE_LABELS[step.step.to_stage]} per {_STAGE_LABELS[step.step.from_stage]}"
        figures[name] = _evidence(name, None, label, "ratio", step.rate, cur)
    findings = [
        {
            "view": f.view,
            "platform": f.subject if f.view == "platform" else None,
            "from_stage": f.from_stage,
            "to_stage": f.to_stage,
            "rate": str(f.rate),
            "previous_rate": str(f.previous_rate),
            "baseline_rate": str(f.baseline_rate),
            "change": str(f.change),
        }
        for f in find_drop_offs(scope, funnel, first, last, rules)
        if f.view in ("whole", "platform")  # channel names are free text: left out
    ]

    store = next(s for s in scope.stores if s.id == product.store_id)
    facts = {
        "reporting_currency": cur,
        "period": {"from": first.isoformat(), "to": last.isoformat(), "days": span},
        "recent_period": {
            "from": recent_first.isoformat(),
            "to": last.isoformat(),
            "days": last.toordinal() - recent_first.toordinal() + 1,
        },
        "product_status": product.status,
        "store_platform": store.provider,
        "connected_ad_platforms": sorted(set(connected)),
        "variants": text_parts["variants"],
        "stock_tracked": text_parts["stock_tracked"],
    }
    store_text = {
        "title": clean(product.title, MAX_TITLE),
        "product_type": clean(product.product_type, MAX_SHORT),
        "vendor": clean(product.vendor, MAX_SHORT),
        "variant_names": [
            t for t in (clean(v, MAX_SHORT) for v in text_parts["variant_titles"]) if t
        ],
    }
    return PlanningContext(
        organization_id=organization_id,
        product_id=product.id,
        store_id=product.store_id,
        currency=cur,
        first=first,
        last=last,
        recent_first=recent_first,
        facts=facts,
        figures=figures,
        findings=findings,
        store_text=store_text,
    )
