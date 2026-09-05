"""
Admin-facing business logic for the Low-Stock Alerts add-on: configuring a
threshold (FR-1) and listing recent alerts (FR-6).

Deliberately separate from `inventory_service.py`: that module owns the
hot, high-concurrency stock-mutation path and the crossing-detection hook
that runs inside it; this module owns the low-frequency admin config/read
path built on top of it. Neither imports the other.
"""
from sqlalchemy.orm import Session

from src.core.exceptions import InvalidRequestError, ProductNotFoundError, WarehouseNotFoundError
from src.core.ids import generate_id
from src.models.inventory import Inventory
from src.models.low_stock_alert import LowStockAlert
from src.repositories import inventory_repository, low_stock_alert_repository, product_repository, warehouse_repository


def set_threshold(db: Session, product_id: str, warehouse_id: str, threshold: int) -> Inventory:
    """
    Set or update the low-stock threshold for a (product, warehouse) pair
    (FR-1). Creates the inventory row on first use, same convention as
    `inventory_service.create_adjustment` -- you can configure alerting for
    a pair before any stock has ever been added to it.
    """
    if threshold < 0:
        raise InvalidRequestError(
            "Low-stock threshold must be non-negative", {"threshold": threshold}
        )
    if product_repository.get_by_id(db, product_id) is None:
        raise ProductNotFoundError(f"Product '{product_id}' was not found", {"product_id": product_id})
    if warehouse_repository.get_by_id(db, warehouse_id) is None:
        raise WarehouseNotFoundError(f"Warehouse '{warehouse_id}' was not found", {"warehouse_id": warehouse_id})

    row = inventory_repository.get(db, product_id, warehouse_id)
    if row is None:
        # A fresh row starts at 0 available, which is always <= any
        # non-negative threshold -- correctly low-stock from the moment
        # it's configured, not a "crossing" that needs an alert (see
        # inventory_repository.set_threshold docstring).
        row = inventory_repository.create(
            db,
            Inventory(
                id=generate_id("inv"),
                product_id=product_id,
                warehouse_id=warehouse_id,
                available_quantity=0,
                reserved_quantity=0,
                low_stock_threshold=threshold,
                is_low_stock=True,
            ),
        )
    else:
        inventory_repository.set_threshold(db, product_id, warehouse_id, threshold)
        db.refresh(row)

    db.commit()
    db.refresh(row)
    return row


def list_alerts(db: Session, *, warehouse_id: str | None = None, limit: int = 100) -> list[LowStockAlert]:
    return low_stock_alert_repository.list_recent(db, warehouse_id=warehouse_id, limit=limit)
