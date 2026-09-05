"""
Reservation expiration scheduler (PRD section 12).

Runs on Celery Beat's schedule (see celery_app.py's `beat_schedule`).
Idempotency (interview Q30, "how do you guarantee that releasing a
reservation twice does not incorrectly increase inventory") comes from two
layers:

  1. `reservation_repository.claim_expired_batch` atomically flips each
     reservation from ACTIVE -> RELEASED in the same statement that selects
     it (`UPDATE ... WHERE status = 'ACTIVE' ... RETURNING *`), so two
     overlapping runs of this task can never both claim the same row.
  2. The order status update below is itself guarded (`order.status ==
     RESERVED`), so a reservation that expires for an order that was
     already separately cancelled/completed doesn't clobber that order's
     real terminal status.
"""
import logging
from datetime import datetime, timezone

from src.database import SessionLocal
from src.logging_config import log_event
from src.models.enums import AuditEventType, OrderStatus
from src.repositories import audit_repository, inventory_repository, order_repository, reservation_repository
from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# How many expired reservations to claim per DB round-trip. Keeps each
# transaction short even if a huge backlog of reservations expired at once
# (e.g. after downtime).
BATCH_SIZE = 100


def expire_reservations() -> int:
    """
    Release every reservation whose `expires_at` has passed. Returns the
    number of reservations released (used by tests and logging). Runs in a
    loop over batches so an unbounded backlog doesn't hold one giant
    transaction open.
    """
    total_released = 0
    while True:
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            claimed = reservation_repository.claim_expired_batch(db, now=now, limit=BATCH_SIZE)
            if not claimed:
                db.commit()
                break

            for reservation in claimed:
                # NOTE: intentionally calling inventory_repository.release
                # directly rather than inventory_service.release_reservation.
                # `claim_expired_batch` already flipped this row's status to
                # RELEASED as part of claiming it, so the service helper's
                # own `WHERE status = 'ACTIVE'` guard would see it as
                # already-released and skip the inventory update entirely.
                # The claiming UPDATE above *is* this reservation's ACTIVE
                # guard; only the inventory-side change is still needed here.
                inventory_repository.release(db, reservation.product_id, reservation.warehouse_id, reservation.quantity)
                audit_repository.record(
                    db,
                    product_id=reservation.product_id,
                    warehouse_id=reservation.warehouse_id,
                    change=reservation.quantity,
                    event_type=AuditEventType.RESERVATION_RELEASED,
                    reference_id=reservation.order_id,
                )
                # Only expire the order if it's still RESERVED -- if it was
                # already cancelled/completed/failed through another path,
                # leave its real terminal status alone.
                order = order_repository.get_by_id_for_update(db, reservation.order_id)
                if order is not None and order.status == OrderStatus.RESERVED:
                    order_repository.update_status(db, order, OrderStatus.EXPIRED)

            db.commit()
            total_released += len(claimed)
            log_event(logger, logging.INFO, "reservations_expired", count=len(claimed))
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return total_released


@celery_app.task(name="workers.expire_reservations")
def expire_reservations_task() -> int:
    return expire_reservations()
