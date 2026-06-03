"""Pagination, sorting and filtering primitives shared by all list endpoints."""

from __future__ import annotations

from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")


class PageParams(BaseModel):
    """Common query params for paginated list endpoints."""

    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)
    sort: str | None = Field(
        default=None,
        description="Comma-separated fields; prefix '-' for desc. e.g. '-created_at,full_name'",
    )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    def parse_sort(self) -> list[tuple[str, bool]]:
        """Return list of (field, is_desc) tuples parsed from ``sort``."""
        if not self.sort:
            return []
        result: list[tuple[str, bool]] = []
        for raw in self.sort.split(","):
            token = raw.strip()
            if not token:
                continue
            if token.startswith("-"):
                result.append((token[1:], True))
            else:
                result.append((token, False))
        return result


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[str | None, Query()] = None,
) -> PageParams:
    """FastAPI dependency producing :class:`PageParams`."""
    return PageParams(page=page, size=size, sort=sort)


class PageMeta(BaseModel):
    page: int
    size: int
    total: int
    pages: int


class Page(BaseModel, Generic[T]):
    """Standard paginated response body."""

    data: list[T]
    meta: PageMeta

    @classmethod
    def create(cls, items: list[T], total: int, params: PageParams) -> Page[T]:
        pages = (total + params.size - 1) // params.size if params.size else 0
        return cls(
            data=items,
            meta=PageMeta(page=params.page, size=params.size, total=total, pages=pages),
        )


class Envelope(BaseModel, Generic[T]):
    """Standard single-object response body: ``{"data": ...}``."""

    data: T
