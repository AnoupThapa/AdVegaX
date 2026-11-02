"""Email address normalization and validation (no external dependency)."""

from __future__ import annotations

import re

_LOCAL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
MAX_LENGTH = 254


def normalize_email(value: str) -> str:
    """Return the canonical (lower-cased, trimmed) address or raise ValueError."""
    email = value.strip().lower()
    if not email or len(email) > MAX_LENGTH or email.count("@") != 1:
        raise ValueError("Enter a valid email address.")
    local, domain = email.split("@")
    labels = domain.split(".")
    if (
        not local
        or len(local) > 64
        or not _LOCAL.match(local)
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or len(labels) < 2
        or not all(_LABEL.match(label) for label in labels)
        or labels[-1].isdigit()
    ):
        raise ValueError("Enter a valid email address.")
    return email
