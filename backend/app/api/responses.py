"""Standard success envelopes (API_SPECIFICATION §2)."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.correlation import get_correlation_id


class Meta(BaseModel):
    request_id: str | None


class ListMeta(Meta):
    page: int
    page_size: int
    total: int


class Envelope[T](BaseModel):
    data: T
    meta: Meta


class ListEnvelope[T](BaseModel):
    data: list[T]
    meta: ListMeta


def ok[T](data: T) -> Envelope[T]:
    return Envelope[T](data=data, meta=Meta(request_id=get_correlation_id()))


def ok_list[T](data: list[T], *, page: int, page_size: int, total: int) -> ListEnvelope[T]:
    return ListEnvelope[T](
        data=data,
        meta=ListMeta(request_id=get_correlation_id(), page=page, page_size=page_size, total=total),
    )
