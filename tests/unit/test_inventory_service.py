"""
Unit tests for the reserve/release/consume primitives in
`inventory_service.py` / `inventory_repository.py`.

These exercise the DB directly (no HTTP layer) since the behaviour under
test is fundamentally about SQL semantics (conditional UPDATE rowcounts),
not request/response handling.
"""
from src.repositories import inventory_repository
from src.services import inventory_service


def test_reserve_succeeds_when_enough_stock(db_session, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=10)

    ok = inventory_service.reserve(
        db_session, product_id=product.id, warehouse_id=warehouse.id, quantity=4, order_id="order_test"
    )
    db_session.commit()

    assert ok is True
    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 6
    assert row.reserved_quantity == 4


def test_reserve_fails_when_not_enough_stock(db_session, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=2)

    ok = inventory_service.reserve(
        db_session, product_id=product.id, warehouse_id=warehouse.id, quantity=5, order_id="order_test"
    )
    db_session.commit()

    assert ok is False
    row = inventory_repository.get(db_session, product.id, warehouse.id)
    # Nothing should have moved.
    assert row.available_quantity == 2
    assert row.reserved_quantity == 0


def test_reserve_never_drives_available_negative(db_session, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=1)

    ok = inventory_service.reserve(
        db_session, product_id=product.id, warehouse_id=warehouse.id, quantity=2, order_id="order_test"
    )
    db_session.commit()

    assert ok is False
    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 1


def test_release_returns_stock_to_available(db_session, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=5, reserved=3)

    ok = inventory_repository.release(db_session, product.id, warehouse.id, 3)
    db_session.commit()

    assert ok is True
    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 8
    assert row.reserved_quantity == 0


def test_consume_only_reduces_reserved(db_session, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=5, reserved=3)

    ok = inventory_repository.consume(db_session, product.id, warehouse.id, 3)
    db_session.commit()

    assert ok is True
    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 5  # unchanged: it was already decremented at reservation time
    assert row.reserved_quantity == 0


def test_adjust_available_rejects_negative_result(db_session, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=5)

    ok = inventory_repository.adjust_available(db_session, product.id, warehouse.id, -10)
    db_session.commit()

    assert ok is False
    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 5


def test_find_best_warehouse_picks_highest_availability(db_session, product):
    from src.core.ids import generate_id
    from src.models.warehouse import Warehouse
    from tests.conftest import make_inventory

    small = Warehouse(id=generate_id("wh"), name="Small", location="A")
    big = Warehouse(id=generate_id("wh"), name="Big", location="B")
    db_session.add_all([small, big])
    db_session.commit()

    make_inventory(db_session, product, small, available=3)
    make_inventory(db_session, product, big, available=20)

    best = inventory_repository.find_best_warehouse(db_session, product.id, quantity=5)
    assert best.warehouse_id == big.id
