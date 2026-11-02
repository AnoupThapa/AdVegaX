"""The campaign strategy's fixed shape (Phase 8, task 8-04, PLAN Q-8-4, Q-8-5).

Two forms of the same shape:

* ``ANSWER_SCHEMA`` — the JSON schema the model's answer is constrained to (structured
  outputs). It uses only what structured outputs support: types, ``enum``, ``required``,
  ``additionalProperties: false`` and ``minItems`` of 1; lengths, counts and ranges are not
  expressible there, so AdVegaX checks them itself (``validation.py``) — the schema narrows
  the answer, it never replaces AdVegaX's checks.
* The limits below, which ``validation.py`` enforces on every answer and on every edit.

A strategy holds **no money amounts**: the model proposes each platform's **share** of the
budget the merchant set; AdVegaX computes the amounts (``budget.py``).
"""

from __future__ import annotations

from typing import Any

OBJECTIVES = ("sales", "leads", "awareness")
PLATFORMS = ("google_ads", "meta_ads")
CAMPAIGN_TYPES: dict[str, tuple[str, ...]] = {
    "google_ads": ("search", "performance_max", "shopping"),
    "meta_ads": ("advantage_plus_shopping", "sales"),
}
ALL_CAMPAIGN_TYPES = tuple(dict.fromkeys(t for ts in CAMPAIGN_TYPES.values() for t in ts))
# What a target may be set for, and the AdVegaX figure it is compared with (the organization's
# own history, Q-8-6). ROAS on the business's figure; cost per order from ad spend and orders.
TARGET_METRICS = ("roas", "cost_per_order", "cost_per_click", "cost_per_conversion")
RISK_CODES = (
    "margin_unknown",
    "margin_negative",
    "low_stock",
    "limited_history",
    "tracking_gap",
    "competition",
    "seasonality",
    "other",
)

# Limits AdVegaX checks (the schema cannot express them).
MAX_SUMMARY = 600
MAX_TEXT = 400
MAX_SHORT = 200
MAX_ANGLES = 6
MAX_TARGETS = 6
MAX_RISKS = 8
MAX_ASSUMPTIONS = 8
MAX_EVIDENCE = 8
SHARE_PLACES = 2  # budget shares are percentages with at most two decimals


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_EVIDENCE = {"type": "array", "items": {"type": "string"}, "minItems": 1}
_TEXT = {"type": "string"}

ANSWER_SCHEMA: dict[str, Any] = _object(
    {
        "objective": {"type": "string", "enum": list(OBJECTIVES)},
        "summary": _TEXT,
        "positioning": _TEXT,
        "platforms": {
            "type": "array",
            "minItems": 1,
            "items": _object(
                {
                    "platform": {"type": "string", "enum": list(PLATFORMS)},
                    "campaign_type": {"type": "string", "enum": list(ALL_CAMPAIGN_TYPES)},
                    "budget_share_percent": {"type": "number"},
                    "audience": _TEXT,
                    "reasoning": _TEXT,
                    "evidence": _EVIDENCE,
                }
            ),
        },
        "angles": {
            "type": "array",
            "minItems": 1,
            "items": _object({"angle": _TEXT, "evidence": _EVIDENCE}),
        },
        "targets": {
            "type": "array",
            "items": _object(
                {
                    "metric": {"type": "string", "enum": list(TARGET_METRICS)},
                    "low": {"type": "number"},
                    "high": {"type": "number"},
                    "evidence": _EVIDENCE,
                }
            ),
        },
        "risks": {
            "type": "array",
            "items": _object({"code": {"type": "string", "enum": list(RISK_CODES)}, "text": _TEXT}),
        },
        "assumptions": {"type": "array", "items": _TEXT},
    }
)
