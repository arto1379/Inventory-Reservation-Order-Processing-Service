"""
Integration tests for the asynchronous order worker (PRD sections 9, 10, 11
plus Bonus A/B). `process_order` is called directly -- no Celery broker or
worker process needed, since it's a plain function (see order_processor.py
module docstring for why that separation exists).
"""
import pytest

from src.models.enums import OrderStatus
from src.repositories import inventory_repository, order_repository
from src.workers.order_processor import RetryablePaymentError, process_order


def _create_order(client, client_headers, product, quantity, payment_token="success", idempotency_key=None):
    headers = dict(client_headers)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    resp = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": product.id, "quantity": quantity}], "payment_token": payment_token},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


def test_successful_payment_completes_order_and_consumes_reservation(
    client, client_headers, product, warehouse, inventory_factory, db_session
):
    inventory_factory(product, warehouse, available=10)
    order = _create_order(client, client_headers, product, quantity=3, payment_token="success")

    process_order(order["id"])

    db_order = order_repository.get_by_id(db_session, order["id"])
    assert db_order.status == OrderStatus.COMPLETED

    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 7  # consumed permanently, not returned
    assert row.reserved_quantity == 0


def test_permanent_failure_releases_reservation(client, client_headers, product, warehouse, inventory_factory, db_session):
    inventory_factory(product, warehouse, available=10)
    order = _create_order(client, client_headers, product, quantity=2, payment_token="fail")

    process_order(order["id"])

    db_order = order_repository.get_by_id(db_session, order["id"])
    assert db_order.status == OrderStatus.FAILED

    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 10  # back to the original amount
    assert row.reserved_quantity == 0


def test_processing_is_idempotent_against_duplicate_delivery(
    client, client_headers, product, warehouse, inventory_factory, db_session
):
    """Simulates the queue delivering the same message twice (e.g. after an
    outbox-relay crash re-publishes it): the second call must be a no-op."""
    inventory_factory(product, warehouse, available=10)
    order = _create_order(client, client_headers, product, quantity=2, payment_token="success")

    process_order(order["id"])
    process_order(order["id"])  # duplicate delivery

    row = inventory_repository.get(db_session, product.id, warehouse.id)
    # If the second call had re-applied the completion logic, reserved_quantity
    # would have gone negative or available would have been double-charged.
    assert row.available_quantity == 8
    assert row.reserved_quantity == 0


def test_retryable_failure_exhausts_attempts_and_writes_dead_letter(
    client, client_headers, product, warehouse, inventory_factory, db_session
):
    from src.config import settings
    from src.models.dead_letter import DeadLetterOrder

    inventory_factory(product, warehouse, available=10)
    order = _create_order(client, client_headers, product, quantity=1, payment_token="fail_retryable")

    # Drive it through every attempt exactly like the Celery wrapper would,
    # minus the actual sleep/broker plumbing.
    for attempt in range(1, settings.payment_max_attempts):
        with pytest.raises(RetryablePaymentError):
            process_order(order["id"])
    process_order(order["id"])  # final attempt: permanent failure

    db_order = order_repository.get_by_id(db_session, order["id"])
    assert db_order.status == OrderStatus.FAILED
    assert db_order.processing_attempts == settings.payment_max_attempts

    dead_letters = db_session.query(DeadLetterOrder).filter_by(order_id=order["id"]).all()
    assert len(dead_letters) == 1
    assert dead_letters[0].attempts == settings.payment_max_attempts

    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 10
    assert row.reserved_quantity == 0
