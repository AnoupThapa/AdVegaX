"""The funnel registry, ``funnel-v1`` (Phase 7, task 7-04, PHASE_07_PLAN §6; A25).

**The one place the funnel is defined** (MASTER §6, D18): each stage, the source it comes from
(Q-7-1) and its definition; each step between two stages and whether it has a rate (Q-7-2).
The API answers carry the version and the web app's "How is this calculated?" comes from here.

Rules shared by every stage and step:

* stages count **events as the platforms report them, not people** (Q-7-5);
* a stage is ``not_synchronized`` when a day of the period was not read for a source in scope
  (or not yet re-read with the funnel figures), ``unavailable`` with a reason when nothing of
  that kind is connected, ``unsupported`` when the connected platform does not report it —
  **never 0** (D18, A10);
* a step's rate is shown only when both stages come from **the same source**; a step across
  sources says so and has no rate — except the store conversion rate (store orders ÷
  Google Analytics sessions), approved in Phase 6;
* ratios are six decimals, half-even; a zero divisor gives a reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

FUNNEL_VERSION = "funnel-v1"

SourceKind = Literal["ads", "google_analytics", "stores", "platform"]
StepKind = Literal["same_source", "different_sources", "store_conversion"]


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    source: SourceKind
    formula: str  # plain words, shown as "How is this calculated?"


@dataclass(frozen=True)
class Step:
    from_stage: str
    to_stage: str
    kind: StepKind


# ------------------------------------------------------------------ the whole business
STAGES: tuple[Stage, ...] = (
    Stage(
        "impressions",
        "Impressions",
        "ads",
        "How often your ads were shown, as Google Ads and Meta report it, added up.",
    ),
    Stage(
        "clicks",
        "Clicks",
        "ads",
        "Clicks on your ads (Google Ads clicks, Meta link clicks), added up.",
    ),
    Stage(
        "landing_page_views",
        "Landing page views",
        "google_analytics",
        "Google Analytics sessions: every visit starts on a landing page. Includes visits "
        "that did not come from ads.",
    ),
    Stage(
        "product_views",
        "Product views",
        "google_analytics",
        "Google Analytics view_item events. Events, not people: one shopper can view several "
        "products.",
    ),
    Stage(
        "adds_to_cart",
        "Adds to cart",
        "google_analytics",
        "Google Analytics add_to_cart events.",
    ),
    Stage(
        "checkouts",
        "Checkouts started",
        "google_analytics",
        "Google Analytics begin_checkout events.",
    ),
    Stage(
        "purchases",
        "Purchases (store orders)",
        "stores",
        "Orders placed in your stores in the period — the business truth.",
    ),
    Stage(
        "analytics_purchases",
        "Purchases (Google Analytics)",
        "google_analytics",
        "Purchases as Google Analytics counts them, shown beside the store orders. Never "
        "added to them.",
    ),
)

STEPS: tuple[Step, ...] = (
    Step("impressions", "clicks", "same_source"),
    Step("clicks", "landing_page_views", "different_sources"),
    Step("landing_page_views", "product_views", "same_source"),
    Step("product_views", "adds_to_cart", "same_source"),
    Step("adds_to_cart", "checkouts", "same_source"),
    Step("checkouts", "analytics_purchases", "same_source"),
    Step("landing_page_views", "purchases", "store_conversion"),
)

# ------------------------------------------------------------------ per ad platform
PLATFORM_STAGES: tuple[Stage, ...] = (
    Stage("impressions", "Impressions", "platform", "Impressions as the platform reports them."),
    Stage(
        "clicks", "Clicks", "platform", "Clicks (Meta: link clicks) as the platform reports them."
    ),
    Stage(
        "landing_page_views",
        "Landing page views",
        "platform",
        "Meta's landing page views: a click after which the page loaded.",
    ),
    Stage("product_views", "Content views", "platform", "Meta's content views."),
    Stage("adds_to_cart", "Adds to cart", "platform", "Meta's adds to cart."),
    Stage("checkouts", "Checkouts started", "platform", "Meta's checkouts initiated."),
    Stage(
        "purchases",
        "Purchases",
        "platform",
        "The platform's own conversions (Meta: purchases; Google Ads: conversions), with its own "
        "attribution. Never added across platforms.",
    ),
)

# The stages each platform reports; the others are "not provided by" it.
PLATFORM_REPORTS: dict[str, tuple[str, ...]] = {
    "meta_ads": tuple(s.key for s in PLATFORM_STAGES),
    "google_ads": ("impressions", "clicks", "purchases"),
}

# ------------------------------------------------------------------ per Google Analytics channel
CHANNEL_STAGES: tuple[Stage, ...] = tuple(
    s
    for s in STAGES
    if s.key
    in ("landing_page_views", "product_views", "adds_to_cart", "checkouts", "analytics_purchases")
)
CHANNEL_STEPS: tuple[Step, ...] = tuple(
    Step(a.key, b.key, "same_source") for a, b in pairwise(CHANNEL_STAGES)
)

# The reason a step's rate is missing when the earlier stage is 0.
ZERO_REASONS: dict[str, str] = {
    "impressions": "no_impressions",
    "clicks": "no_clicks",
    "landing_page_views": "no_sessions",
    "product_views": "no_product_views",
    "adds_to_cart": "no_adds_to_cart",
    "checkouts": "no_checkouts",
}
