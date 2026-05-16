from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    items: list[T]
    total: int
    next_cursor: str | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
