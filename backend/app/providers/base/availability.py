"""Data availability (A10): unavailable data is never represented as zero."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class Availability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"  # the platform could provide it but not for this account/state
    UNSUPPORTED = "unsupported"  # the platform does not provide it
    NOT_SYNCHRONIZED = "not_synchronized"  # not synchronized yet, or stale


@dataclass(frozen=True)
class MetricValue:
    """A value from a provider together with its availability and provenance."""

    value: Decimal | None
    availability: Availability
    source: str
    as_of: datetime | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if self.availability is Availability.AVAILABLE and self.value is None:
            raise ValueError("an available metric must carry a value")
        if self.availability is not Availability.AVAILABLE and self.value is not None:
            raise ValueError("a metric that is not available must not carry a value")

    @classmethod
    def available(
        cls,
        value: Decimal,
        *,
        source: str,
        as_of: datetime | None = None,
        currency: str | None = None,
    ) -> MetricValue:
        return cls(value, Availability.AVAILABLE, source, as_of, currency)

    @classmethod
    def missing(cls, availability: Availability, *, source: str) -> MetricValue:
        return cls(None, availability, source)
