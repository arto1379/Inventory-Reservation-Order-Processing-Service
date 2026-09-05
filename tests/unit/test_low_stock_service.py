"""
Unit tests for the Low-Stock Alerts add-on's state transitions (PRD section
2/8, required tests 1-6). These call `inventory_service`/`low_stock_service`
directly against a real Postgres row (no HTTP layer) since the behavior
under test is fundamentally about the atomic-UPDATE crossing detection in
`inventory_repository.py`, not request/response handling.

Required test 7 (concurrent reductions -> no duplicate alerts) lives in
`tests/concurrency/test_concurrent_low_stock_alerts.py`.
"""
import pytest

from src.core.exceptions import InvalidRequestError
from src.repositories import inventory_repository, low_stock_alert_repository
from src.schemas.inventory import InventoryAdjustmentRequest
from src.services import inventory_service, low_stock_service


def _reserve(db_session, product, warehouse, quantity, order_id="order_test"):
    ok = inventory_service.reserve(
        db_session, product_id=product.id, warehouse_id=warehouse.id, quantity=quantity, order_id=order_id
    )
    db_session.commit()
    return ok


def _restock(db_session, product, warehouse, quantity):
    inventory_service.create_adjustment(
        db_session,
        InventoryAdjustmentRequest(
            product_id=product.id, warehouse_id=warehouse.id, quantity=quantity, reason="restock"
        ),
    )


def test_quantity_stays_above_threshold_no_alert(db_session, product, warehouse, inventory_factory):
    """Required test 1."""
    inventory_factory(product, warehouse, available=8, low_stock_threshold=5)

    assert _reserve(db_session, product, warehouse, 1) is True  # 8 -> 7

    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 7
    assert row.is_low_stock is False
    assert low_stock_alert_repository.list_recent(db_session) == []


def test_quantity_crossing_threshold_creates_one_alert(db_session, product, warehouse, inventory_factory):
    """Required test 2, and the PRD's own worked example (7 -> 5)."""
    inventory_factory(product, warehouse, available=7, low_stock_threshold=5)

    assert _reserve(db_session, product, warehouse, 2) is True  # 7 -> 5

    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.is_low_stock is True
    alerts = low_stock_alert_repository.list_recent(db_session)
    assert len(alerts) == 1
    assert alerts[0].product_id == product.id
    assert alerts[0].warehouse_id == warehouse.id
    assert alerts[0].quantity_at_alert == 5
    assert alerts[0].threshold == 5


def test_further_decrease_while_low_stock_does_not_realert(db_session, product, warehouse, inventory_factory):
    """Required test 3."""
    inventory_factory(product, warehouse, available=6, low_stock_threshold=5)

    assert _reserve(db_session, product, warehouse, 1) is True  # 6 -> 5, crosses: alert #1
    assert _reserve(db_session, product, warehouse, 1) is True  # 5 -> 4, still low: no new alert
    assert _reserve(db_session, product, warehouse, 1) is True  # 4 -> 3, still low: no new alert

    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 3
    assert row.is_low_stock is True
    alerts = low_stock_alert_repository.list_recent(db_session)
    assert len(alerts) == 1
    assert alerts[0].quantity_at_alert == 5


def test_restock_above_threshold_resets_low_stock_state(db_session, product, warehouse, inventory_factory):
    """Required test 4."""
    inventory_factory(product, warehouse, available=8, low_stock_threshold=5)
    _reserve(db_session, product, warehouse, 3)  # 8 -> 5, crosses into low-stock
    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.is_low_stock is True

    _restock(db_session, product, warehouse, 10)  # 5 -> 15

    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 15
    assert row.is_low_stock is False


def test_quantity_crossing_threshold_again_creates_new_alert(db_session, product, warehouse, inventory_factory):
    """Required test 5, chaining the full PRD example: 8->7 (no alert),
    7->5 (alert), restock 3->15 (reset), 15->5 (alert again)."""
    inventory_factory(product, warehouse, available=8, low_stock_threshold=5)

    _reserve(db_session, product, warehouse, 1)  # 8 -> 7, no alert
    _reserve(db_session, product, warehouse, 2)  # 7 -> 5, alert #1
    _reserve(db_session, product, warehouse, 1)  # 5 -> 4, no new alert
    _reserve(db_session, product, warehouse, 1)  # 4 -> 3, no new alert
    _restock(db_session, product, warehouse, 12)  # 3 -> 15, resets
    _reserve(db_session, product, warehouse, 10)  # 15 -> 5, alert #2

    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 5
    assert row.is_low_stock is True
    alerts = low_stock_alert_repository.list_recent(db_session)
    assert len(alerts) == 2
    assert all(a.quantity_at_alert == 5 and a.threshold == 5 for a in alerts)


def test_negative_threshold_rejected_by_service(db_session, product, warehouse):
    """Required test 6."""
    with pytest.raises(InvalidRequestError):
        low_stock_service.set_threshold(db_session, product.id, warehouse.id, -1)


def test_set_threshold_creates_inventory_row_when_none_exists(db_session, product, warehouse):
    row = low_stock_service.set_threshold(db_session, product.id, warehouse.id, 5)

    assert row.available_quantity == 0
    assert row.low_stock_threshold == 5
    assert row.is_low_stock is True  # 0 available is always <= a non-negative threshold


def test_set_threshold_recomputes_state_without_alerting(db_session, product, warehouse, inventory_factory):
    """Reconfiguring the threshold around an unchanged quantity is not a
    'crossing' (FR-2) -- it should update state silently, not alert."""
    inventory_factory(product, warehouse, available=4)

    row = low_stock_service.set_threshold(db_session, product.id, warehouse.id, 5)

    assert row.is_low_stock is True
    assert low_stock_alert_repository.list_recent(db_session) == []


def test_list_alerts_filters_by_warehouse(db_session, product, warehouse, inventory_factory):
    from src.core.ids import generate_id
    from src.models.warehouse import Warehouse

    other_warehouse = Warehouse(id=generate_id("wh"), name="Other", location="Elsewhere")
    db_session.add(other_warehouse)
    db_session.commit()

    inventory_factory(product, warehouse, available=6, low_stock_threshold=5)
    inventory_factory(product, other_warehouse, available=6, low_stock_threshold=5)
    _reserve(db_session, product, warehouse, 2)  # 6 -> 4, alert in `warehouse`
    inventory_service.reserve(db_session, product_id=product.id, warehouse_id=other_warehouse.id, quantity=2, order_id="o2")
    db_session.commit()  # 6 -> 4, alert in `other_warehouse`

    scoped = low_stock_alert_repository.list_recent(db_session, warehouse_id=warehouse.id)
    assert len(scoped) == 1
    assert scoped[0].warehouse_id == warehouse.id

    all_alerts = low_stock_alert_repository.list_recent(db_session)
    assert len(all_alerts) == 2
