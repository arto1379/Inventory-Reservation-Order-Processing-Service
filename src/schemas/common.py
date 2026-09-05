"""Shared response envelopes: error format and pagination metadata."""
from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    """Matches the consistent error envelope required by PRD section 17."""

    error: ErrorDetail


class PaginationMeta(BaseModel):
    page: int
    limit: int
    total: int
    total_pages: int
