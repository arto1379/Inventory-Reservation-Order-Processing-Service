"""
Low-Stock Alerts bonus extension (PRD section 9): notify the warehouse team
when a `LowStockAlertCreated` event reaches the queue via the outbox relay.

    Inventory Update -> Threshold Crossing Detected -> LowStockAlert Created
    -> Queue Event (outbox) -> Notification Worker (this module)

This simulates notifying the warehouse team by logging the event -- no new
table, since the `low_stock_alerts` row written in the same transaction as
the crossing (see `inventory_service._check_low_stock_transition`) is
already the durable record of the alert; this worker's only job is the
"tell someone" side effect.

Idempotency note (interview Q4, "what if this processes the same event
twice?"): the outbox relay guarantees at-least-once delivery, the same
trade-off as order processing (see docs/decisions/0003-outbox-pattern.md).
Unlike `process_order`, this task has no state to corrupt by running
twice -- logging the same already-true fact again is harmless, so no
idempotency guard is needed here.
"""
import logging

from src.logging_config import log_event
from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.notify_low_stock")
def notify_low_stock_task(payload: dict) -> None:
    log_event(
        logger, logging.WARNING, "low_stock_alert_notified",
        alert_id=payload["alert_id"], product_id=payload["product_id"], warehouse_id=payload["warehouse_id"],
        quantity_at_alert=payload["quantity_at_alert"], threshold=payload["threshold"],
    )
