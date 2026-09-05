"""
Structured (JSON) application logging.

Every log line is emitted as a single JSON object so it can be shipped to
any log aggregator (CloudWatch, Datadog, ELK, ...) without a parsing layer.
The current request's correlation ID (see `src/middleware/request_id.py`) is
automatically attached to every log record via a logging filter, so logs
from a single request can be grepped/joined together even across the async
worker boundary (the worker re-uses the same request ID it was handed).

Sensitive fields (passwords, tokens, secrets) are never logged anywhere in
this codebase -- see `core/security.py` and the auth routes, which log only
user IDs/emails, never credentials.
"""
import json
import logging
import sys
from contextvars import ContextVar

from src.config import settings

# Holds the current request's correlation ID for the lifetime of that
# request/task. Defaults to "-" outside of a request (e.g. at startup).
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Injects the current contextvar request ID into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Renders log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        # Allow call sites to pass structured extra fields, e.g.
        # logger.info("inventory_reserved", extra={"order_id": ..., "quantity": ...})
        for key, value in record.__dict__.items():
            if key in ("event_data",):
                payload.update(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Install the JSON formatter/filter on the root logger. Call once at startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    # Quiet down noisy third-party loggers unless we're debugging.
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, level: int, event: str, **fields) -> None:
    """
    Convenience helper for emitting a structured event log, e.g.:

        log_event(logger, logging.INFO, "inventory_reserved",
                   order_id=order.id, product_id=product_id, quantity=qty)
    """
    logger.log(level, event, extra={"event_data": fields})
