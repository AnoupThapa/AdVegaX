"""What each platform accepts (Phase 9, task 9-03, PLAN Q-9-4; A27).

* **Google Ads responsive search ad** (``google_rsa``): 3 to 15 headlines of up to 30 characters,
  2 to 4 descriptions of up to 90, two display-path fields of up to 15 (may be empty) — Google Ads
  Help, "About responsive search ads" (checked 2026-10-26). Double-width characters (Chinese,
  Japanese, Korean) count as 2.
* **Meta single image or text ad** (``meta_single``): up to 5 primary texts, 5 headlines and 5
  descriptions; AdVegaX uses Meta's **recommended** lengths as its limits (primary text 125,
  headline 40, description 30) so text is not cut off; a call to action from a fixed list
  (Marketing API names). From a summary of Meta's Ads Guide — Step 0 re-checks them.

A content dict has exactly these fields. Lists hold short lines of text.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

GOOGLE, META = "google_ads", "meta_ads"
FORMAT_OF = {GOOGLE: "google_rsa", META: "meta_single"}
CALLS_TO_ACTION = {
    "SHOP_NOW": "Shop now",
    "LEARN_MORE": "Learn more",
    "ORDER_NOW": "Order now",
    "GET_QUOTE": "Get quote",
    "CONTACT_US": "Contact us",
    "SIGN_UP": "Sign up",
}


@dataclass(frozen=True)
class ListField:
    name: str
    minimum: int
    maximum: int
    length: int  # characters per line


@dataclass(frozen=True)
class TextField:
    name: str
    length: int
    required: bool


@dataclass(frozen=True)
class Spec:
    format: str
    lists: tuple[ListField, ...]
    texts: tuple[TextField, ...]
    choices: dict[str, tuple[str, ...]]

    @property
    def fields(self) -> tuple[str, ...]:
        return (
            *(f.name for f in self.lists),
            *(f.name for f in self.texts),
            *self.choices,
        )


SPECS: dict[str, Spec] = {
    "google_rsa": Spec(
        format="google_rsa",
        lists=(ListField("headlines", 3, 15, 30), ListField("descriptions", 2, 4, 90)),
        texts=(TextField("path1", 15, False), TextField("path2", 15, False)),
        choices={},
    ),
    "meta_single": Spec(
        format="meta_single",
        lists=(
            ListField("primary_texts", 1, 5, 125),
            ListField("headlines", 1, 5, 40),
            ListField("descriptions", 0, 5, 30),
        ),
        texts=(),
        choices={"call_to_action": tuple(CALLS_TO_ACTION)},
    ),
}


def length(text: str) -> int:
    """Characters as the platforms count them: wide (CJK) characters count as 2."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)
