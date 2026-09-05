"""
Required test 7 (Low-Stock Alerts PRD section 8): concurrent reductions
must not create duplicate alerts for the same threshold crossing.

Same shape as `tests/concurrency/test_concurrent_reservation.py` (real
threads, each with its own DB connection, each calling the exact function
`order_service.create_order` uses) -- this proves
`inventory_repository.try_flip_low_stock`'s compare-and-swap guard holds
under genuine concurrent access, not just sequential calls. See
`docs/decisions/0005-low-stock-alerts.md` for why this is safe.
"""
import concurrent.futures

import pytest

from src.database import SessionLocal
from src.repositories import inventory_repository, low_stock_alert_repository
from src.services import inventory_service

NUM_CONCURRENT_REQUESTS = 100
STARTING_INVENTORY = 10
LOW_STOCK_THRESHOLD = 5


def _attempt_reserve(product_id: str, warehouse_id: str, index: int) -> bool:
    session = SessionLocal()
    try:
        reserved = inventory_service.reserve(
            session, product_id=product_id, warehouse_id=warehouse_id, quantity=1, order_id=f"order_lowstock_{index}"
        )
        session.commit()
        return reserved
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.mark.concurrency
def test_concurrent_reductions_create_exactly_one_low_stock_alert(product, warehouse, inventory_factory, db_session):
    inventory_factory(product, warehouse, available=STARTING_INVENTORY, low_stock_threshold=LOW_STOCK_THRESHOLD)

    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        futures = [
            executor.submit(_attempt_reserve, product.id, warehouse.id, i) for i in range(NUM_CONCURRENT_REQUESTS)
        ]
        results = [f.result() for f in futures]

    assert sum(1 for r in results if r) == STARTING_INVENTORY

    db_session.expire_all()
    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 0
    assert row.is_low_stock is True

    alerts = low_stock_alert_repository.list_recent(db_session)
    assert len(alerts) == 1, "exactly one alert must be created for the single crossing at threshold=5"
    assert alerts[0].quantity_at_alert == LOW_STOCK_THRESHOLD
    assert alerts[0].threshold == LOW_STOCK_THRESHOLD
