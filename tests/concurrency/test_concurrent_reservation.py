"""
The concurrency test required by PRD section 25:

    Starting inventory: 10 units
    Send: 100 simultaneous requests, each reserving 1 unit
    Expected: 10 successful reservations, 90 failures,
              final available inventory = 0, never negative.

This exercises the DB-level guarantee directly (each simulated "request" is
a real thread with its own database connection calling
`inventory_service.reserve`, the same function `order_service.create_order`
uses) rather than going through the HTTP layer, so the test is fast and
isolates exactly the property PRD section 7 asks us to prove: the
conditional-UPDATE strategy in `inventory_repository.try_reserve` is safe
under genuine concurrent access to the same row. See that module's
docstring for why this is correct without SELECT FOR UPDATE or SERIALIZABLE
isolation.
"""
import concurrent.futures

import pytest

from src.database import SessionLocal
from src.repositories import inventory_repository
from src.services import inventory_service

NUM_CONCURRENT_REQUESTS = 100
STARTING_INVENTORY = 10


def _attempt_reserve(product_id: str, warehouse_id: str, index: int) -> bool:
    """Runs in its own thread with its own DB session/connection -- this is
    what makes it a genuine concurrency test rather than a sequential loop."""
    session = SessionLocal()
    try:
        reserved = inventory_service.reserve(
            session, product_id=product_id, warehouse_id=warehouse_id, quantity=1, order_id=f"order_concurrency_{index}"
        )
        session.commit()
        return reserved
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.mark.concurrency
def test_concurrent_reservations_cannot_oversell_inventory(product, warehouse, inventory_factory, db_session):
    inventory_factory(product, warehouse, available=STARTING_INVENTORY)

    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        futures = [
            executor.submit(_attempt_reserve, product.id, warehouse.id, i) for i in range(NUM_CONCURRENT_REQUESTS)
        ]
        results = [f.result() for f in futures]

    successes = sum(1 for r in results if r)
    failures = sum(1 for r in results if not r)

    assert successes == STARTING_INVENTORY, "exactly as many reservations as available stock must succeed"
    assert failures == NUM_CONCURRENT_REQUESTS - STARTING_INVENTORY

    # `db_session` may hold a stale cached copy of the inventory row from
    # before the concurrent writes happened on other connections; expire it
    # so the assertions below issue a fresh SELECT.
    db_session.expire_all()
    row = inventory_repository.get(db_session, product.id, warehouse.id)
    assert row.available_quantity == 0
    assert row.available_quantity >= 0  # the invariant that must never be violated
    assert row.reserved_quantity == STARTING_INVENTORY
