"""Offset pagination.

Offset paging is the right call at this scale: result sets are per-user or per-day
and small. The envelope is shaped so it can be swapped for cursor paging later
without changing the client's read of ``items``/``has_next``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")

MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    has_next: bool


def paginate(session: Session, statement: Select, params: PageParams) -> tuple[list, int]:
    """Run ``statement`` for one page. Returns ``(rows, total)``."""
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    rows = session.execute(statement.limit(params.page_size).offset(params.offset)).scalars().all()
    return list(rows), int(total or 0)


def build_page(items: list, total: int, params: PageParams) -> dict:
    return {
        "items": items,
        "page": params.page,
        "page_size": params.page_size,
        "total": total,
        "has_next": params.offset + len(items) < total,
    }
