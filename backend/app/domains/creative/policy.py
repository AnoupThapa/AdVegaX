"""The fixed checks every creative passes before it can be approved (9-03, PLAN Q-9-5; A27).

Deterministic and explainable — no AI. Each result is ``{code, field, detail, severity}``:

* ``block`` — the creative cannot be approved until it is fixed;
* ``flag`` — allowed, but a person must confirm they checked it (a superlative claim).

Checks, in order:

1. **Shape and limits** (``specs.py``): exactly the format's fields; counts; characters per
   line (wide characters count 2); an allowed call to action; no control characters.
2. **No duplicate lines** within a field.
3. **Google only:** no phone numbers, e-mail addresses or web addresses in the text, no emoji.
4. **No shouting:** no word of three or more letters in capitals (unless it is one of the
   organization's allowed words, e.g. a brand), no ``!!`` or ``??``.
5. **Prohibited terms:** AdVegaX's base list for health and medical claims (relevant to
   healthcare and PPE products; e.g. Australia's TGA advertising rules) plus the
   organization's own list; whole words, any case.
6. **Prices:** every price in the text must equal one of the product's catalogue prices.
7. **Superlatives** ("best", "#1", "cheapest", …) are flagged.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domains.creative.specs import SPECS, length

BLOCK, FLAG = "block", "flag"

# Health and medical claims a merchant of consumables, healthcare and PPE products must not
# make in ads (curative or absolute-protection claims, claimed regulator approval).
BASE_PROHIBITED = (
    "cure",
    "cures",
    "cured",
    "heals",
    "miracle",
    "100% effective",
    "100% protection",
    "100% safe",
    "guaranteed protection",
    "complete protection",
    "kills covid",
    "kills viruses",
    "kills all germs",
    "virus-proof",
    "virus proof",
    "covid-proof",
    "prevents covid",
    "prevents infection",
    "clinically proven",
    "tga approved",
    "fda approved",
    "doctor recommended",
    "risk-free",
    "no side effects",
)
SUPERLATIVES = ("best", "#1", "number one", "cheapest", "lowest price", "world's leading")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PHONE = re.compile(r"(?<!\w)\+?\(?\d[\d\s().-]{6,}\d(?!\w)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_WEB = re.compile(
    r"(?i)\b(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|io|co|au|np|shop|store)\b"
)
_EMOJI = re.compile("[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f900-\U0001f9ff⭐⭕️]")
_CAPS = re.compile(r"\b[A-Z]{3,}\b")
_REPEATED = re.compile(r"[!?]{2,}")
_PRICE = re.compile(
    r"(?i)(?:(?:A|AU|US|NZ|NPR|Rs\.?|AUD|USD|NZD)\s?\$?|\$)\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    r"|(\d+(?:\.\d{1,2})?)\s?(?:AUD|USD|NZD|NPR|dollars?)\b"
)


def _result(
    code: str, field: str, severity: str = BLOCK, detail: str | None = None
) -> dict[str, Any]:
    return {"code": code, "field": field, "detail": detail, "severity": severity}


def _lines(spec_format: str, content: dict[str, Any]) -> Iterator[tuple[str, str]]:
    spec = SPECS[spec_format]
    for f in spec.lists:
        for i, line in enumerate(content.get(f.name) or []):
            if isinstance(line, str):
                yield f"{f.name}[{i}]", line
    for t in spec.texts:
        value = content.get(t.name)
        if isinstance(value, str) and value:
            yield t.name, value


def _term(term: str) -> re.Pattern[str]:
    edge = r"(?<![\w])" if term[0].isalnum() else ""
    tail = r"(?![\w])" if term[-1].isalnum() else ""
    return re.compile(edge + re.escape(term) + tail, re.IGNORECASE)


def shape_results(spec_format: str, content: Any) -> list[dict[str, Any]]:
    spec = SPECS[spec_format]
    if not isinstance(content, dict) or set(content) != set(spec.fields):
        return [_result("shape", "content")]
    out: list[dict[str, Any]] = []
    for f in spec.lists:
        lines = content[f.name]
        if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
            out.append(_result("shape", f.name))
            continue
        if len(lines) < f.minimum:
            out.append(_result("too_few", f.name, detail=str(f.minimum)))
        if len(lines) > f.maximum:
            out.append(_result("too_many", f.name, detail=str(f.maximum)))
        for i, line in enumerate(lines):
            where = f"{f.name}[{i}]"
            if not line.strip():
                out.append(_result("empty", where))
            elif length(line) > f.length:
                out.append(_result("too_long", where, detail=str(f.length)))
    for t in spec.texts:
        value = content[t.name]
        if not isinstance(value, str):
            out.append(_result("shape", t.name))
        elif t.required and not value.strip():
            out.append(_result("empty", t.name))
        elif length(value) > t.length:
            out.append(_result("too_long", t.name, detail=str(t.length)))
        elif value and not re.fullmatch(r"[\w-]+", value):
            out.append(_result("invalid_path", t.name))  # a display path is one word
    for name, allowed in spec.choices.items():
        if content[name] not in allowed:
            out.append(_result("unknown_value", name))
    return out


def check(
    spec_format: str,
    content: Any,
    *,
    prohibited: list[str],
    allowed_caps: list[str],
    prices: list[Decimal],
) -> list[dict[str, Any]]:
    """Every result for one creative's content; [] = nothing to fix or confirm."""
    out = shape_results(spec_format, content)
    if any(r["code"] == "shape" for r in out):
        return out
    lines = list(_lines(spec_format, content))
    for where, line in lines:
        if _CONTROL.search(line):
            out.append(_result("invalid_text", where))
    spec = SPECS[spec_format]
    for f in spec.lists:
        seen: set[str] = set()
        for i, line in enumerate(content[f.name]):
            key = " ".join(line.lower().split())
            if key and key in seen:
                out.append(_result("duplicate", f"{f.name}[{i}]"))
            seen.add(key)
    google = spec_format == "google_rsa"
    allowed = {w.upper() for w in allowed_caps}
    terms = [*BASE_PROHIBITED, *(t.strip().lower() for t in prohibited if t.strip())]
    catalogue = {p.quantize(Decimal("0.01")) for p in prices}
    for where, line in lines:
        if google:
            if _EMAIL.search(line):
                out.append(_result("email_address", where))
            elif _WEB.search(line):
                out.append(_result("web_address", where))
            if _PHONE.search(line):
                out.append(_result("phone_number", where))
            if _EMOJI.search(line):
                out.append(_result("emoji", where))
        for word in _CAPS.findall(line):
            if word not in allowed:
                out.append(_result("all_caps", where, detail=word))
                break
        if _REPEATED.search(line):
            out.append(_result("repeated_punctuation", where))
        for term in dict.fromkeys(terms):
            if _term(term).search(line):
                out.append(_result("prohibited_term", where, detail=term))
        for match in _PRICE.finditer(line):
            raw = (match.group(1) or match.group(2) or "").replace(",", "")
            try:
                amount = Decimal(raw).quantize(Decimal("0.01"))
            except InvalidOperation:  # pragma: no cover - the pattern only matches numbers
                continue
            if amount not in catalogue:
                out.append(_result("price_not_in_catalogue", where, detail=str(amount)))
        for word in SUPERLATIVES:
            if _term(word).search(line):
                out.append(_result("superlative", where, FLAG, word))
    return out


def blocking(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in results if r["severity"] == BLOCK]


def flags(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in results if r["severity"] == FLAG]
