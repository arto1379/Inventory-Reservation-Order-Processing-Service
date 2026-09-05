"""
Application-level exception hierarchy.

Every business-rule failure raises one of these instead of returning ad-hoc
HTTP responses from inside service/repository code (which shouldn't know
anything about HTTP). A single FastAPI exception handler
(`src/middleware/error_handler.py`) catches `AppError` and renders it using
the consistent error envelope required by the PRD:

    {"error": {"code": "...", "message": "...", "details": {...}}}

Keeping this separate from the web layer also means the same exceptions can
be raised (and asserted on in tests) from the Celery workers, which have no
HTTP context at all.
"""
from typing import Any


class AppError(Exception):
    """Base class for all handled application errors."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class InvalidRequestError(AppError):
    status_code = 400
    code = "INVALID_REQUEST"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class ProductNotFoundError(AppError):
    status_code = 404
    code = "PRODUCT_NOT_FOUND"


class WarehouseNotFoundError(AppError):
    status_code = 404
    code = "WAREHOUSE_NOT_FOUND"


class OrderNotFoundError(AppError):
    status_code = 404
    code = "ORDER_NOT_FOUND"


class InsufficientInventoryError(AppError):
    status_code = 409
    code = "INSUFFICIENT_INVENTORY"


class DuplicateSkuError(AppError):
    status_code = 409
    code = "DUPLICATE_SKU"


class OrderCannotBeCancelledError(AppError):
    status_code = 409
    code = "ORDER_CANNOT_BE_CANCELLED"


class IdempotencyConflictError(AppError):
    """Raised when a second request with the same key arrives while the
    first one is still being processed (see idempotency_service.py)."""

    status_code = 409
    code = "IDEMPOTENCY_KEY_IN_PROGRESS"


class InternalError(AppError):
    status_code = 500
    code = "INTERNAL_ERROR"
