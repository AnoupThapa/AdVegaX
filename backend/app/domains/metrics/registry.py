"""The unified metric registry, ``analytics-v1`` (Phase 6, task 6-04, PHASE_06_PLAN §6; A24).

**The one place unified figures are defined** (MASTER §7, D17): each metric's inputs, formula,
unit, availability rules and sources. The API answers carry the version and the web app's
"How is this calculated?" text comes from here, never from a page.

Rules shared by every metric (A5, A10, Q-6-3 … Q-6-12):

* amounts are in the organization's **reporting currency**; each source's figure is converted
  with **its own day's** exchange rate (``app/domains/fx``) before anything is added;
* days are **each source's own days** (Q-6-4): a store's 5 October and an ad account's
  5 October are the same report day;
* a figure is ``not_synchronized`` when a day of the period was not read for a source in scope,
  ``unavailable`` with a reason when an input is missing (no product cost, no exchange rate,
  orders in another currency, nothing connected of that kind), ``unsupported`` when no
  connected platform provides it — **never 0**;
* ratios are derived on read (six decimals, half-even); a zero divisor gives a reason;
* platform conversion values are **never added across platforms** and Google Analytics
  figures are never added to store or ad figures; users are never added across days.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DEFINITION_VERSION = "analytics-v1"

Unit = Literal["money", "count", "ratio", "multiple", "decimal"]


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: Unit
    formula: str  # plain words, shown as "How is this calculated?"
    sources: tuple[str, ...]  # stores | ads | google_analytics
    note: str | None = None


_STORE = ("stores",)
_ADS = ("ads",)
_BOTH = ("stores", "ads")
_GA = ("google_analytics",)

METRICS: tuple[Metric, ...] = (
    Metric(
        "net_sales",
        "Net sales",
        "money",
        "The stores' sales after discounts and returns, before tax and shipping (finance-v1), "
        "added up over the period.",
        _STORE,
    ),
    Metric("orders", "Orders", "count", "The stores' orders placed in the period.", _STORE),
    Metric(
        "product_cost",
        "Product cost",
        "money",
        "Quantity x unit cost of every product sold, minus returned items, from the store "
        "platform. Not available when any item sold in the period has no cost.",
        _STORE,
    ),
    Metric("gross_profit", "Gross profit", "money", "Net sales - product cost.", _STORE),
    Metric("gross_margin", "Gross margin", "ratio", "Gross profit / net sales.", _STORE),
    Metric(
        "ad_spend",
        "Ad spend",
        "money",
        "What Google Ads and Meta report as spent, for every ad account in scope, converted "
        "to the reporting currency with each day's rate and added up.",
        _ADS,
    ),
    Metric(
        "profit_after_ad_spend",
        "Profit after ad spend",
        "money",
        "Gross profit - ad spend.",
        _BOTH,
        note="Before shipping costs and payment fees, which the store platforms do not provide.",
    ),
    Metric(
        "blended_roas",
        "Blended ROAS",
        "multiple",
        "Net sales / ad spend: what every unit of currency spent on ads returned in sales, "
        "across all platforms. No attribution is needed.",
        _BOTH,
    ),
    Metric("cost_per_order", "Cost per order", "money", "Ad spend / orders.", _BOTH),
    Metric("ad_spend_share", "Ad spend share of sales", "ratio", "Ad spend / net sales.", _BOTH),
    Metric(
        "shipping_cost",
        "Shipping cost",
        "money",
        "What shipping costs the business. Not provided by Shopify or WooCommerce.",
        _STORE,
    ),
    Metric(
        "payment_fees",
        "Payment fees",
        "money",
        "What payment providers charge. Not provided by Shopify or WooCommerce.",
        _STORE,
    ),
    Metric(
        "contribution_profit",
        "Contribution profit",
        "money",
        "Profit after ad spend - shipping costs - payment fees. Shown once those costs can be "
        "entered.",
        _BOTH,
    ),
    Metric(
        "customer_acquisition_cost",
        "Customer acquisition cost",
        "money",
        "Ad spend / new customers. New customers are not identified yet.",
        _BOTH,
    ),
    Metric(
        "sessions",
        "Sessions",
        "count",
        "Google Analytics sessions of every property in scope, added up.",
        _GA,
    ),
    Metric(
        "analytics_purchases",
        "Purchases (Google Analytics)",
        "count",
        "Purchases as Google Analytics reports them. Never added to store orders.",
        _GA,
    ),
    Metric(
        "analytics_revenue",
        "Purchase revenue (Google Analytics)",
        "money",
        "Purchase revenue (minus refunds) as Google Analytics reports it, converted with each "
        "day's rate. Never added to store sales.",
        _GA,
    ),
    Metric(
        "store_conversion_rate",
        "Store conversion rate",
        "ratio",
        "Store orders / Google Analytics sessions. Only when every store in scope has a "
        "Google Analytics property.",
        ("stores", "google_analytics"),
    ),
)

BY_KEY: dict[str, Metric] = {m.key: m for m in METRICS}

# Figures no connected platform provides in v1 (Q-6-7, Q-6-8): their availability and reason.
NOT_PROVIDED: dict[str, tuple[str, str]] = {
    "shipping_cost": ("unsupported", "not_provided_by_platform"),
    "payment_fees": ("unsupported", "not_provided_by_platform"),
    "contribution_profit": ("unsupported", "costs_not_entered"),
    "customer_acquisition_cost": ("unavailable", "customer_key_not_collected"),
}

# ---------------------------------------------------------------- table figures (6-08)
# The figures of the channels, campaigns and products tables, defined here too so "How is
# this calculated?" is never hand-written on a page. Each table's answer carries its own list.

_PLATFORM_FIGURES: tuple[Metric, ...] = (
    Metric(
        "spend",
        "Spend",
        "money",
        "What the platform reports as spent, converted to the reporting currency with each "
        "day's rate and added up.",
        _ADS,
    ),
    Metric("clicks", "Clicks", "count", "Clicks as the platform reports them.", _ADS),
    Metric(
        "impressions", "Impressions", "count", "Impressions as the platform reports them.", _ADS
    ),
    Metric(
        "conversions",
        "Conversions",
        "decimal",
        "Conversions as the platform counts them, with its own attribution. Never added "
        "across platforms or to store orders.",
        _ADS,
    ),
    Metric(
        "conversion_value",
        "Conversion value",
        "money",
        "The value the platform gives its conversions, converted with each day's rate. Never "
        "added across platforms or to store sales.",
        _ADS,
    ),
    Metric(
        "platform_roas",
        "Platform ROAS",
        "multiple",
        "Conversion value / spend, as the platform attributes it. Not comparable with blended "
        "ROAS, which uses store sales.",
        _ADS,
    ),
    Metric("cost_per_click", "Cost per click", "money", "Spend / clicks.", _ADS),
    Metric("cost_per_conversion", "Cost per conversion", "money", "Spend / conversions.", _ADS),
)

_ANALYTICS_FIGURES: tuple[Metric, ...] = (
    Metric("sessions", "Sessions", "count", "Sessions as Google Analytics reports them.", _GA),
    Metric(
        "engaged_sessions",
        "Engaged sessions",
        "count",
        "Sessions Google Analytics counts as engaged.",
        _GA,
    ),
    Metric("engagement_rate", "Engagement rate", "ratio", "Engaged sessions / sessions.", _GA),
    Metric(
        "key_events", "Key events", "decimal", "Key events as Google Analytics counts them.", _GA
    ),
    Metric(
        "purchases",
        "Purchases",
        "count",
        "Purchases as Google Analytics reports them. Never added to store orders.",
        _GA,
    ),
    Metric(
        "purchase_revenue",
        "Purchase revenue",
        "money",
        "Purchase revenue (minus refunds) as Google Analytics reports it, converted with each "
        "day's rate. Never added to store sales.",
        _GA,
    ),
)

_BUDGET_USE = Metric(
    "budget_use",
    "Budget use",
    "ratio",
    "Spend in the period / (today's daily budget x days in the period). Not shown for "
    "lifetime or shared budgets.",
    _ADS,
    note="Uses today's budget for every day, as the platforms do not keep budget history.",
)

_PRODUCT_FIGURES: tuple[Metric, ...] = (
    Metric(
        "units",
        "Units sold",
        "count",
        "Quantity sold minus quantity returned in the period.",
        _STORE,
    ),
    Metric(
        "net_sales",
        "Net sales",
        "money",
        "The product's sales after discounts and returns, before tax and shipping (finance-v1).",
        _STORE,
    ),
    Metric(
        "product_cost",
        "Product cost",
        "money",
        "Quantity x unit cost, minus returned items. Not available when any sold item has no cost.",
        _STORE,
    ),
    Metric("gross_profit", "Gross profit", "money", "Net sales - product cost.", _STORE),
    Metric("gross_margin", "Gross margin", "ratio", "Gross profit / net sales.", _STORE),
)

# The definitions each table's answer carries.
TABLES: dict[str, tuple[Metric, ...]] = {
    "channels": _PLATFORM_FIGURES + _ANALYTICS_FIGURES,
    "campaigns": (
        *_PLATFORM_FIGURES,
        _BUDGET_USE,
        *(m for m in _ANALYTICS_FIGURES if m.key in ("sessions", "purchases", "purchase_revenue")),
    ),
    "products": _PRODUCT_FIGURES,
}
