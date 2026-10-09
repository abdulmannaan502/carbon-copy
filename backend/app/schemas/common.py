from math import ceil
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
    pages: int

    @classmethod
    def build(cls, items: list[T], params: PageParams, total: int) -> "Page[T]":
        return cls(
            items=items,
            page=params.page,
            page_size=params.page_size,
            total=total,
            pages=ceil(total / params.page_size) if total else 0,
        )
