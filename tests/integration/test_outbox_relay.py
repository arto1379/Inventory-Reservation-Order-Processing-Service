"""
Integration test for the transactional outbox pattern (Bonus C).

Verifies the two halves of the guarantee described in
`src/models/outbox.py` and `src/workers/outbox_relay.py`:
  1. Creating an order writes a PENDING outbox row in the same transaction.
  2. Relaying that row actually results in the order being processed (here,
     via Celery's eager mode -- see conftest.py's `_celery_eager_mode` --
     so no real broker/worker process is needed for the assertion).
"""
from src.models.enums import OutboxStatus
from src.repositories import order_repository
from src.workers.outbox_relay import relay_once


def test_order_creation_writes_pending_outbox_event(client, client_headers, product, warehouse, inventory_factory, db_session):
    from src.models.outbox import OutboxEvent

    inventory_factory(product, warehouse, available=10)
    order = client.post(
        "/api/v1/orders", json={"items": [{"product_id": product.id, "quantity": 1}]}, headers=client_headers
    ).json()

    events = db_session.query(OutboxEvent).filter_by(aggregate_id=order["id"]).all()
    assert len(events) == 1
    assert events[0].status == OutboxStatus.PENDING
    assert events[0].event_type == "ORDER_RESERVED"


def test_relay_publishes_event_and_triggers_order_processing(
    client, client_headers, product, warehouse, inventory_factory, db_session
):
    from src.models.enums import OrderStatus
    from src.models.outbox import OutboxEvent

    inventory_factory(product, warehouse, available=10)
    order = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": product.id, "quantity": 1}], "payment_token": "success"},
        headers=client_headers,
    ).json()

    published_count = relay_once()
    assert published_count == 1

    event = db_session.query(OutboxEvent).filter_by(aggregate_id=order["id"]).one()
    assert event.status == OutboxStatus.PUBLISHED
    assert event.published_at is not None

    # Eager Celery execution means process_order already ran synchronously
    # inside relay_once() -> process_order_task.delay(...).
    db_order = order_repository.get_by_id(db_session, order["id"])
    assert db_order.status == OrderStatus.COMPLETED
