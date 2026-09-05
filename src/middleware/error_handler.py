"""
Global exception handlers producing the consistent error envelope required
by PRD section 17:

    {"error": {"code": "...", "message": "...", "details": {...}}}

Registered once in `src/main.py`. Three cases are handled:

  1. `AppError` (and subclasses) -- our own domain errors, rendered with
     their declared status code/code/message/details.
  2. `RequestValidationError` -- FastAPI/Pydantic request validation
     failures, normalized to our INVALID_REQUEST shape instead of FastAPI's
     default `{"detail": [...]}` format.
  3. Anything else -- an unexpected bug. Logged with a full stack trace
     (server-side only) and returned to the client as a generic
     INTERNAL_ERROR with no internal details leaked.
"""
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.core.exceptions import AppError

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Request validation failed",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra={"event_data": {"path": request.url.path}})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred", "details": {}}},
        )
