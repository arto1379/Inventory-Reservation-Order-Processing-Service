"""
Asynchronous order processing (PRD section 9): simulate payment, then
finalize the order and its inventory reservations.

Design notes (see README for the full write-up):

  - `process_order` is a plain function with no Celery dependency, so it can
    be unit/integration tested by calling it directly -- no broker, no
    worker process, no network needed.
  - Duplicate delivery safety (interview Q29): the very first thing this
    function does is lock the order row and check `status == RESERVED`.
    Since a successful run atomically transitions the order away from
    RESERVED before doing anything else, a second delivery of the *same*
    message (from an at-least-once queue, or from the outbox relay
    re-publishing after a crash -- see outbox_relay.py) always finds a
    non-RESERVED status and safely no-ops.
  - Retry attempts are tracked in the database (`orders.processing_attempts`)
    rather than only in Celery's in-memory retry counter, so the attempt
    count survives a worker restart and is directly inspectable/auditable.
"""
import logging

from sqlalchemy.orm import Session

from src.config import settings
from src.database import SessionLocal
from src.logging_config import log_event
from src.models.enums import OrderStatus, PaymentResult
from src.models.order import Order
from src.repositories import dead_letter_repository, order_repository, reservation_repository
from src.services import inventory_service, payment_service
from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


class RetryablePaymentError(Exception):
    """Raised to signal the Celery task wrapper to reschedule this order
    for another attempt after `countdown` seconds (Bonus A backoff)."""

    def __init__(self, message: str, countdown: int):
        super().__init__(message)
        self.countdown = countdown


def process_order(order_id: str) -> None:
    """
    Process one order: simulate payment, then either complete it (consuming
    its reservations) or fail it (releasing its reservations). Idempotent
    against duplicate invocation for the same order_id -- see module
    docstring.
    """
    db = SessionLocal()
    try:
        order = order_repository.get_by_id_for_update(db, order_id)
        if order is None or order.status != OrderStatus.RESERVED:
            # Nothing to do: unknown order, or already handled by a prior
            # delivery of this same message (or the order was cancelled /
            # expired out from under us before we got to it).
            db.commit()
            return

        order.processing_attempts += 1
        attempt = order.processing_attempts
        payment_token = order.payment_token
        order_repository.update_status(db, order, OrderStatus.PROCESSING)
        db.commit()
        log_event(logger, logging.INFO, "order_processing_started", order_id=order_id, attempt=attempt)

        outcome = payment_service.charge(payment_token)

        # Re-lock: the commit above ended the previous transaction/lock.
        # Only this worker acts on PROCESSING orders, so the row is exactly
        # as we left it.
        order = order_repository.get_by_id_for_update(db, order_id)

        if outcome.result == PaymentResult.SUCCESS:
            _complete_order(db, order_id, order)
            log_event(logger, logging.INFO, "order_completed", order_id=order_id, attempt=attempt)
            return

        if outcome.retryable and attempt < settings.payment_max_attempts:
            # Put the order back into RESERVED so the next attempt's guard
            # above (status == RESERVED) picks it up correctly, then ask
            # the Celery wrapper to retry with the configured backoff delay.
            order_repository.update_status(db, order, OrderStatus.RESERVED)
            db.commit()
            backoff = settings.payment_retry_backoff_list
            countdown = backoff[attempt - 1] if attempt - 1 < len(backoff) else backoff[-1]
            log_event(
                logger, logging.WARNING, "order_payment_retry_scheduled",
                order_id=order_id, attempt=attempt, countdown=countdown,
            )
            raise RetryablePaymentError(outcome.message, countdown=countdown)

        # Permanent failure: either a non-retryable decline, or we've
        # exhausted PAYMENT_MAX_ATTEMPTS retries.
        _fail_order(db, order_id, order)
        log_event(logger, logging.WARNING, "order_failed", order_id=order_id, attempt=attempt, reason=outcome.message)

        if attempt >= settings.payment_max_attempts:
            # Bonus B: repeatedly-failing orders get a dead-letter record
            # for operator investigation.
            dead_letter_repository.record(db, order_id=order_id, reason=outcome.message, attempts=attempt)
            db.commit()
    except RetryablePaymentError:
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _complete_order(db: Session, order_id: str, order: Order) -> None:
    for reservation in reservation_repository.list_active_for_order(db, order_id):
        inventory_service.consume_reservation(db, reservation, order_id=order_id)
    order_repository.update_status(db, order, OrderStatus.COMPLETED)
    db.commit()


def _fail_order(db: Session, order_id: str, order: Order) -> None:
    for reservation in reservation_repository.list_active_for_order(db, order_id):
        inventory_service.release_reservation(db, reservation, reference_id=order_id)
    order_repository.update_status(db, order, OrderStatus.FAILED)
    db.commit()


@celery_app.task(bind=True, name="workers.process_order")
def process_order_task(self, order_id: str) -> None:
    """Celery entrypoint. Delegates all logic to `process_order`; only
    responsible for translating a `RetryablePaymentError` into an actual
    scheduled Celery retry."""
    try:
        process_order(order_id)
    except RetryablePaymentError as exc:
        raise self.retry(exc=exc, countdown=exc.countdown, max_retries=settings.payment_max_attempts)
