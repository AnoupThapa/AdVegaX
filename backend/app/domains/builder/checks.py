"""The campaign builder's checks (Phase 10B, task 10B-02, Q-10B-2 … Q-10B-7, Q-10B-10).

Pure functions over what the service gathered (``DraftFacts``). The groups, in order:

* **creative** — the creative is approved, for this platform, from this strategy, and the
  strategy is ready and plans this platform;
* **keywords** (Google) — 1 to 20, Google's length, word and character limits, no
  duplicates, none of the organization's prohibited words;
* **targeting** — supported countries; Meta ages 18 to 65;
* **landing_page** — https, on the store's own domain, no credentials or odd ports;
* **budget** — the currency's decimals, at least the platform minimum, at most the
  organization's maximum (which must be chosen);
* **meta** — a Facebook Page (and optionally a pixel) as numeric Meta IDs;
* **declaration** — the person confirmed the platforms' declarations;
* **limits** — the ad account's changes for the day.

Each is recorded with its result; later groups are skipped after a failure (as in 10A).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import urlsplit

from app.domains.actions.catalogue import quantum
from app.domains.actions.validation import Check
from app.providers.base.changes import COUNTRIES

MAX_KEYWORDS = 20
KEYWORD_CHARS = 80  # Google: keyword text up to 80 characters and 10 words
KEYWORD_WORDS = 10
MATCHES = ("phrase", "exact", "broad")
# Characters Google refuses in keywords (its keyword policy; to confirm in Step 0).
_BAD_KEYWORD = re.compile(r"[!@%^*()={};~`<>?\\|,]")
_META_ID = re.compile(r"^[0-9]{5,25}$")
MAX_NAME = 200


@dataclass(frozen=True)
class DraftFacts:
    platform: str
    name: str
    daily_budget: Decimal
    currency: str
    locations: list[str]
    age_min: int
    age_max: int
    keywords: list[dict[str, str]]
    landing_url: str
    meta_page_id: str | None
    meta_pixel_id: str | None
    declared: bool
    # the creative and strategy
    creative_status: str
    creative_platform: str
    creative_from_strategy: bool
    strategy_status: str
    strategy_platforms: list[str]
    meta_image: bool  # a Meta creative has an image
    # the organization and store
    store_hosts: list[str]
    prohibited: list[str] = field(default_factory=list)
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    maximum_set: bool = False
    volume_used: int = 0
    volume_limit: int = 50
    resource_reason: str | None = None


def _creative(f: DraftFacts) -> list[str]:
    if f.resource_reason:
        return [f.resource_reason]
    if f.strategy_status != "ready":
        return ["strategy_not_ready"]
    if f.platform not in f.strategy_platforms:
        return ["platform_not_in_strategy"]
    if not f.creative_from_strategy or f.creative_platform != f.platform:
        return ["creative_not_for_this_campaign"]
    if f.creative_status != "approved":
        return ["creative_not_approved"]
    if f.platform == "meta_ads" and not f.meta_image:
        return ["image_required"]
    if not f.name.strip() or len(f.name) > MAX_NAME:
        return ["name_invalid"]
    return []


def keyword_reasons(keywords: list[dict[str, str]], prohibited: list[str]) -> list[str]:
    if not keywords:
        return ["keywords_required"]
    if len(keywords) > MAX_KEYWORDS:
        return ["too_many_keywords"]
    reasons: list[str] = []
    seen: set[tuple[str, str]] = set()
    for i, k in enumerate(keywords):
        text = " ".join(str(k.get("text", "")).split()).lower()
        match = k.get("match", "")
        if match not in MATCHES:
            reasons.append(f"match_type_invalid:{i}")
        elif not text or len(text) > KEYWORD_CHARS or len(text.split()) > KEYWORD_WORDS:
            reasons.append(f"keyword_too_long:{i}" if text else f"keyword_empty:{i}")
        elif _BAD_KEYWORD.search(text):
            reasons.append(f"keyword_characters:{i}")
        elif (text, match) in seen:
            reasons.append(f"keyword_duplicate:{i}")
        elif any(re.search(rf"\b{re.escape(p)}\b", text) for p in prohibited):
            reasons.append(f"keyword_prohibited:{i}")
        seen.add((text, match))
    return reasons


def _targeting(f: DraftFacts) -> list[str]:
    reasons = []
    if not f.locations or len(f.locations) > len(COUNTRIES):
        reasons.append("locations_required")
    elif any(c not in COUNTRIES for c in f.locations) or len(set(f.locations)) != len(f.locations):
        reasons.append("location_not_supported")
    if f.platform == "meta_ads" and not 18 <= f.age_min <= f.age_max <= 65:
        reasons.append("ages_invalid")
    return reasons


def landing_reason(url: str, hosts: list[str]) -> str | None:
    if not url or len(url) > 2048:
        return "landing_url_required"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "landing_url_invalid"
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or not host:
        return "landing_url_not_https"
    if parts.username or parts.password or port not in (None, 443):
        return "landing_url_invalid"
    allowed = {h.lower().rstrip(".") for h in hosts if h}
    if not any(host == h or host.endswith(f".{h}") for h in allowed):
        return "landing_url_not_store"
    return None


def _budget(f: DraftFacts) -> list[str]:
    reasons = []
    if f.daily_budget <= 0 or f.daily_budget != f.daily_budget.quantize(quantum(f.currency)):
        return ["daily_budget_invalid"]
    if f.minimum is None:
        reasons.append("minimum_not_checkable")
    elif f.daily_budget < f.minimum:
        reasons.append("below_platform_minimum")
    if not f.maximum_set:
        reasons.append("maximum_not_set")
    elif f.maximum is None:
        reasons.append("maximum_not_checkable")
    elif f.daily_budget > f.maximum:
        reasons.append("above_maximum")
    return reasons


def _meta(f: DraftFacts) -> list[str]:
    if f.platform != "meta_ads":
        return []
    reasons = []
    if not f.meta_page_id or not _META_ID.fullmatch(f.meta_page_id):
        reasons.append("page_required")
    if f.meta_pixel_id is not None and not _META_ID.fullmatch(f.meta_pixel_id):
        reasons.append("pixel_invalid")
    return reasons


def run(f: DraftFacts) -> list[Check]:
    out: list[Check] = []
    failed = False

    def add(name: str, reasons: list[str]) -> None:
        nonlocal failed
        if failed:
            out.append(Check(name, "skipped"))
        elif reasons:
            out.extend(Check(name, "failed", r) for r in reasons)
            failed = True
        else:
            out.append(Check(name, "passed"))

    add("creative", _creative(f))
    if f.platform == "google_ads":
        add("keywords", keyword_reasons(f.keywords, f.prohibited))
    add("targeting", _targeting(f))
    landing = landing_reason(f.landing_url, f.store_hosts)
    add("landing_page", [landing] if landing else [])
    add("budget", _budget(f))
    add("meta", _meta(f))
    add("declaration", [] if f.declared else ["declaration_required"])
    add("limits", ["daily_limit_reached"] if f.volume_used >= f.volume_limit else [])
    return out
