"""
Business logic for inventory: manual adjustments, retrieval, and the
reserve/release/consume operations that back order processing.

Note on transaction boundaries: the `reserve_*` / `release_*` / `consume_*`
helpers below deliberately do NOT call `db.commit()`. They are building
blocks composed by `order_service.py` and the workers inside a single
larger transaction (e.g. "reserve every line item of an order, or none of
them"). Only the top-level caller that owns the unit of work commits.
`create_adjustment` is the exception: FR-3 is a standalone endpoint, so it
owns its own transaction and commits directly.
"""
from sqlalchemy.orm import Session

from src.core.exceptions import InvalidRequestError, ProductNotFoundError, WarehouseNotFoundError
from src.core.ids import generate_id
from src.models.enums import AuditEventType
from src.models.inventory import Inventory
from src.models.reservation import InventoryReservation
from src.repositories import (
    audit_repository,
    inventory_repository,
    product_repository,
    reservation_repository,
    warehouse_repository,
)
from src.schemas.inventory import InventoryAdjustmentRequest, ProductInventoryResponse, WarehouseInventoryLine


def get_inventory_for_product(db: Session, product_id: str) -> ProductInventoryResponse:
    if product_repository.get_by_id(db, product_id) is None:
        _raise_product_not_found(product_id)
    rows = inventory_repository.list_for_product(db, product_id)
    return ProductInventoryResponse(
        product_id=product_id,
        warehouses=[
            WarehouseInventoryLine(warehouse_id=r.warehouse_id, available=r.available_quantity, reserved=r.reserved_quantity)
            for r in rows
        ],
    )


def create_adjustment(db: Session, payload: InventoryAdjustmentRequest) -> Inventory:
    """
    Apply a manual/warehouse-delivery adjustment (FR-3). Creates the
    (product, warehouse) inventory row on first use (quantity must be >= 0
    in that case, since you cannot remove stock that was never added).
    Every adjustment writes an immutable audit record in the same
    transaction as the stock change, so the two can never diverge.
    """
    if product_repository.get_by_id(db, payload.product_id) is None:
        _raise_product_not_found(payload.product_id)
    if warehouse_repository.get_by_id(db, payload.warehouse_id) is None:
        raise WarehouseNotFoundError(
            f"Warehouse '{payload.warehouse_id}' was not found", {"warehouse_id": payload.warehouse_id}
        )

    row = inventory_repository.get(db, payload.product_id, payload.warehouse_id)
    if row is None:
        if payload.quantity < 0:
            raise InvalidRequestError(
                "Cannot apply a negative adjustment to inventory that does not exist yet",
                {"product_id": payload.product_id, "warehouse_id": payload.warehouse_id},
            )
        row = inventory_repository.create(
            db,
            Inventory(
                id=generate_id("inv"),
                product_id=payload.product_id,
                warehouse_id=payload.warehouse_id,
                available_quantity=payload.quantity,
                reserved_quantity=0,
            ),
        )
    else:
        ok = inventory_repository.adjust_available(db, payload.product_id, payload.warehouse_id, payload.quantity)
        if not ok:
            raise InvalidRequestError(
                "Adjustment would drive available inventory below zero",
                {"product_id": payload.product_id, "warehouse_id": payload.warehouse_id, "quantity": payload.quantity},
            )
        db.refresh(row)

    event_type = AuditEventType.STOCK_ADDED if payload.quantity >= 0 else AuditEventType.STOCK_REMOVED
    audit_repository.record(
        db,
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        change=payload.quantity,
        event_type=event_type,
        reference_id=payload.reason,
    )
    db.commit()
    db.refresh(row)
    return row


def reserve(db: Session, *, product_id: str, warehouse_id: str, quantity: int, order_id: str) -> bool:
    """Attempt to move stock from available -> reserved and log the audit
    event. Returns False (does not raise) if there wasn't enough stock, so
    the caller (order_service) can roll back the whole order atomically."""
    ok = inventory_repository.try_reserve(db, product_id, warehouse_id, quantity)
    if ok:
        audit_repository.record(
            db,
            product_id=product_id,
            warehouse_id=warehouse_id,
            change=-quantity,
            event_type=AuditEventType.INVENTORY_RESERVED,
            reference_id=order_id,
        )
    return ok


def release_reservation(db: Session, reservation: InventoryReservation, *, reference_id: str) -> bool:
    """Release one reservation's held stock back to available. Idempotency
    is enforced by `reservation_repository.mark_released` (ACTIVE-only
    guard); if it returns False here, this reservation was already released
    or consumed by a concurrent process and we correctly do nothing."""
    if not reservation_repository.mark_released(db, reservation.id):
        return False
    inventory_repository.release(db, reservation.product_id, reservation.warehouse_id, reservation.quantity)
    audit_repository.record(
        db,
        product_id=reservation.product_id,
        warehouse_id=reservation.warehouse_id,
        change=reservation.quantity,
        event_type=AuditEventType.RESERVATION_RELEASED,
        reference_id=reference_id,
    )
    return True


def consume_reservation(db: Session, reservation: InventoryReservation, *, order_id: str) -> bool:
    """Permanently consume one reservation's held stock (order completed)."""
    if not reservation_repository.mark_consumed(db, reservation.id):
        return False
    inventory_repository.consume(db, reservation.product_id, reservation.warehouse_id, reservation.quantity)
    audit_repository.record(
        db,
        product_id=reservation.product_id,
        warehouse_id=reservation.warehouse_id,
        change=-reservation.quantity,
        event_type=AuditEventType.ORDER_COMPLETED,
        reference_id=order_id,
    )
    return True


def _raise_product_not_found(product_id: str) -> None:
    raise ProductNotFoundError(f"Product '{product_id}' was not found", {"product_id": product_id})
