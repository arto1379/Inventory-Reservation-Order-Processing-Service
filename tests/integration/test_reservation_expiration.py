"""
Integration tests for the reservation-expiration scheduler (PRD section 12).
"""
from datetime import datetime, timedelta, timezone

from src.models.enums import OrderStatus, ReservationStatus
from src.repositories import inventory_repository, order_repository, reservation_repository
from src.workers.reservation_cleanup import expire_reservations


def _create_order(client, client_headers, product, quantity):
    resp = client.post(
        "/api/v1/orders", json={"items": [{"product_id": product.id, "quantity": quantity}]}, headers=client_headers
    )
    assert resp.status_code == 201
    return resp.json()


def _force_expire(db_session, order_id: str) -> None:
    """Back-date the order's reservation(s) as if RESERVATION_TIMEOUT_MINUTES
    had already elapsed, without waiting in real time."""
    for reservation in reservation_repository.list_active_for_order(db_session, order_id):
        reservation.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()


def test_expired_reservation_releases_inventory_and_expires_order(
    client, client_headers, product, warehouse, inventory_factory, db_session
):
    inventory_factory(product, warehouse, available=10)
    order = _create_order(client, client_headers, product, quantity=4)
    _force_expire(db_session, order["id"])

    released_count = expire_reservations()

    assert released_count == 1
    db_order = order_repository.get_by_id(db_session, order["id"])
    assert db_order.status == OrderStatus.EXPIRED

    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 10
    assert row.reserved_quantity == 0


def test_running_expiration_twice_does_not_double_release(
    client, client_headers, product, warehouse, inventory_factory, db_session
):
    inventory_factory(product, warehouse, available=10)
    order = _create_order(client, client_headers, product, quantity=4)
    _force_expire(db_session, order["id"])

    first_run = expire_reservations()
    second_run = expire_reservations()

    assert first_run == 1
    assert second_run == 0  # nothing left to claim; already RELEASED

    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 10  # not 14 -- proves no double-release
    assert row.reserved_quantity == 0


def test_expiration_does_not_touch_already_cancelled_orders(
    client, client_headers, product, warehouse, inventory_factory, db_session
):
    inventory_factory(product, warehouse, available=10)
    order = _create_order(client, client_headers, product, quantity=2)

    # Cancel it first (this already releases the reservation through the
    # normal cancellation path), then simulate the scheduler catching up on
    # a reservation row that's already RELEASED.
    client.post(f"/api/v1/orders/{order['id']}/cancel", headers=client_headers)

    released_count = expire_reservations()

    assert released_count == 0
    db_order = order_repository.get_by_id(db_session, order["id"])
    assert db_order.status == OrderStatus.CANCELLED  # untouched, not overwritten to EXPIRED
