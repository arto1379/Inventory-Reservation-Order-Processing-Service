"""
Outbox relay process (Bonus C — Transactional Outbox Pattern).

A standalone long-running process (its own docker-compose service) that
polls the `outbox_events` table for rows written by `order_service.py`
inside the same transaction as order creation, and publishes each one onto
the Celery queue. Only marked PUBLISHED *after* the Celery `.delay()` call
returns successfully, so a crash between "read PENDING row" and "mark
PUBLISHED" simply leaves the row PENDING -- the next poll re-publishes it.
This trades an occasional duplicate delivery (handled by the idempotent
order worker, see order_processor.py) for the guarantee that a committed
order can never fail to be enqueued at all, which directly answers
interview question 28.

Run with: `python -m src.workers.outbox_relay`
"""
import logging
import signal
import time
from types import FrameType

from src.config import settings
from src.database import SessionLocal
from src.logging_config import configure_logging, log_event
from src.repositories import outbox_repository
from src.workers.low_stock_notifier import notify_low_stock_task
from src.workers.order_processor import process_order_task

logger = logging.getLogger(__name__)

BATCH_SIZE = 50

# Maps an outbox event_type to the Celery task that should handle it. A
# dict dispatch table keeps this open to more event types later without
# touching the polling loop itself.
_HANDLERS = {
    "ORDER_RESERVED": lambda payload: process_order_task.delay(payload["order_id"]),
    "LOW_STOCK_ALERT_CREATED": lambda payload: notify_low_stock_task.delay(payload),
}

_shutdown_requested = False


def _handle_shutdown_signal(signum: int, frame: FrameType | None) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def relay_once() -> int:
    """Publish a single batch of pending outbox events. Returns how many
    were published. Exposed separately from the loop so tests can call it
    synchronously without spinning up a background thread."""
    db = SessionLocal()
    try:
        events = outbox_repository.claim_pending_batch(db, BATCH_SIZE)
        for event in events:
            handler = _HANDLERS.get(event.event_type)
            if handler is None:
                logger.warning("No outbox handler registered for event_type=%s", event.event_type)
                continue
            handler(event.payload)
            outbox_repository.mark_published(db, event.id)
        db.commit()
        if events:
            log_event(logger, logging.INFO, "outbox_events_published", count=len(events))
        return len(events)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_forever() -> None:
    configure_logging()
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    logger.info("Outbox relay started, polling every %ss", settings.outbox_poll_interval_seconds)

    while not _shutdown_requested:
        try:
            relay_once()
        except Exception:
            logger.exception("Outbox relay poll failed, will retry next interval")
        time.sleep(settings.outbox_poll_interval_seconds)

    logger.info("Outbox relay shutting down")


if __name__ == "__main__":
    run_forever()
