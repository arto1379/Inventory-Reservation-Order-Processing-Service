"""
Integration test for the Low-Stock Alerts bonus extension (PRD section 9):
the crossing writes a transactional outbox event, and the relay publishes
it to the notification worker -- same two-halves shape as
`tests/integration/test_outbox_relay.py` for order processing.
"""
import logging

from src.models.enums import OutboxStatus
from src.models.outbox import OutboxEvent
from src.services import inventory_service
from src.workers.outbox_relay import relay_once


def test_crossing_writes_pending_outbox_event(db_session, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=7, low_stock_threshold=5)

    inventory_service.reserve(db_session, product_id=product.id, warehouse_id=warehouse.id, quantity=2, order_id="o1")
    db_session.commit()

    events = db_session.query(OutboxEvent).filter_by(event_type="LOW_STOCK_ALERT_CREATED").all()
    assert len(events) == 1
    assert events[0].status == OutboxStatus.PENDING
    assert events[0].aggregate_type == "low_stock_alert"
    assert events[0].payload["product_id"] == product.id
    assert events[0].payload["warehouse_id"] == warehouse.id
    assert events[0].payload["quantity_at_alert"] == 5
    assert events[0].payload["threshold"] == 5


def test_relay_publishes_event_and_notifier_logs_it(db_session, product, warehouse, inventory_factory, caplog):
    inventory_factory(product, warehouse, available=7, low_stock_threshold=5)
    inventory_service.reserve(db_session, product_id=product.id, warehouse_id=warehouse.id, quantity=2, order_id="o1")
    db_session.commit()

    with caplog.at_level(logging.WARNING):
        published_count = relay_once()

    assert published_count == 1
    event = db_session.query(OutboxEvent).filter_by(event_type="LOW_STOCK_ALERT_CREATED").one()
    assert event.status == OutboxStatus.PUBLISHED
    assert event.published_at is not None

    # Eager Celery execution means notify_low_stock_task already ran
    # synchronously inside relay_once() -> notify_low_stock_task.delay(...).
    assert any(record.message == "low_stock_alert_notified" for record in caplog.records)
