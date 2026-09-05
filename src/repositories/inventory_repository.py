"""
Data access for the `inventory` table.

*** This module implements the core concurrency guarantee of the whole
service (PRD section 7). Read this docstring before touching anything here. ***

Strategy chosen: atomic conditional UPDATE ("compare-and-swap"), not
`SELECT ... FOR UPDATE` + separate `UPDATE`.

    UPDATE inventory
    SET available_quantity = available_quantity - :qty,
        reserved_quantity  = reserved_quantity + :qty
    WHERE product_id = :pid AND warehouse_id = :wid
      AND available_quantity >= :qty

Why this is safe under concurrency: a single `UPDATE` statement is itself
atomic from Postgres's point of view. When two transactions race to update
the same row, Postgres serializes them at the row level: the second
transaction's `UPDATE` blocks until the first commits (or rolls back), then
re-evaluates its own `WHERE available_quantity >= :qty` against the
*post-commit* value -- not the value it originally read. So if transaction A
reserves the last unit, transaction B's `WHERE` clause fails to match (0
rows updated) and we correctly report insufficient inventory, with zero risk
of a lost-update race. This holds under Postgres's default READ COMMITTED
isolation level, so no `SERIALIZABLE` transactions or manual advisory locks
are needed.

Why not `SELECT ... FOR UPDATE`: it is also correct, but it holds a row lock
for the entire duration of the surrounding transaction (product validation,
order insert, reservation insert, audit log insert, ...), which serializes
unrelated work and increases the chance of lock-wait timeouts under load.
The conditional UPDATE achieves the same correctness guarantee while
minimizing lock hold time to a single statement.

Every mutating function here returns a boolean/rowcount rather than raising
on failure -- the caller (inventory_service) decides what "0 rows affected"
means in context (insufficient stock vs. "already released", etc.), which
keeps this module a thin, honest data-access layer.
"""
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.models.inventory import Inventory


def get(db: Session, product_id: str, warehouse_id: str) -> Inventory | None:
    return db.execute(
        select(Inventory).where(Inventory.product_id == product_id, Inventory.warehouse_id == warehouse_id)
    ).scalar_one_or_none()


def list_for_product(db: Session, product_id: str) -> list[Inventory]:
    return list(db.execute(select(Inventory).where(Inventory.product_id == product_id)).scalars().all())


def find_best_warehouse(db: Session, product_id: str, quantity: int) -> Inventory | None:
    """
    Pick which warehouse fulfils a line item (see README > "How warehouse
    selection works"): the warehouse with the most available stock that can
    satisfy the full requested quantity on its own. Orders are not split
    across multiple warehouses for a single line item, keeping shipment
    logic (out of scope here) simple for whoever builds it next.
    """
    return db.execute(
        select(Inventory)
        .where(Inventory.product_id == product_id, Inventory.available_quantity >= quantity)
        .order_by(Inventory.available_quantity.desc())
        .limit(1)
    ).scalar_one_or_none()


def total_available(db: Session, product_id: str) -> int:
    """Total available quantity across all warehouses, used only to build a
    helpful `{"requested": x, "available": y}` error detail payload."""
    rows = list_for_product(db, product_id)
    return sum(row.available_quantity for row in rows)


def try_reserve(db: Session, product_id: str, warehouse_id: str, quantity: int) -> bool:
    """Atomically move `quantity` units from available -> reserved. Returns
    False (no rows changed) if there wasn't enough available stock."""
    stmt = (
        update(Inventory)
        .where(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
            Inventory.available_quantity >= quantity,
        )
        .values(
            available_quantity=Inventory.available_quantity - quantity,
            reserved_quantity=Inventory.reserved_quantity + quantity,
        )
    )
    result = db.execute(stmt)
    return result.rowcount == 1


def release(db: Session, product_id: str, warehouse_id: str, quantity: int) -> bool:
    """Atomically move `quantity` units from reserved back -> available
    (order failed, cancelled, or its reservation expired)."""
    stmt = (
        update(Inventory)
        .where(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
            Inventory.reserved_quantity >= quantity,
        )
        .values(
            available_quantity=Inventory.available_quantity + quantity,
            reserved_quantity=Inventory.reserved_quantity - quantity,
        )
    )
    result = db.execute(stmt)
    return result.rowcount == 1


def consume(db: Session, product_id: str, warehouse_id: str, quantity: int) -> bool:
    """Permanently consume `quantity` reserved units (order completed).
    `available_quantity` was already decremented at reservation time, so
    only `reserved_quantity` moves here."""
    stmt = (
        update(Inventory)
        .where(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
            Inventory.reserved_quantity >= quantity,
        )
        .values(reserved_quantity=Inventory.reserved_quantity - quantity)
    )
    result = db.execute(stmt)
    return result.rowcount == 1


def adjust_available(db: Session, product_id: str, warehouse_id: str, delta: int) -> bool:
    """
    Apply a signed manual adjustment (FR-3, e.g. a warehouse delivery or a
    damaged-goods write-off) to available_quantity. Guarded so a large
    negative adjustment can never drive stock below zero; the CHECK
    constraint on the table is the final backstop if this guard were ever
    bypassed.
    """
    stmt = (
        update(Inventory)
        .where(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
            Inventory.available_quantity + delta >= 0,
        )
        .values(available_quantity=Inventory.available_quantity + delta)
    )
    result = db.execute(stmt)
    return result.rowcount == 1


def create(db: Session, inventory: Inventory) -> Inventory:
    db.add(inventory)
    db.flush()
    return inventory
