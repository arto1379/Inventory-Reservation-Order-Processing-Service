"""
Data access for the `inventory_reservations` table.

The release/consume helpers use the same conditional-UPDATE pattern as
`inventory_repository.py`: `WHERE status = 'ACTIVE'` guards every state
transition, which is what makes releasing (or consuming) a reservation
*idempotent* -- running it twice (e.g. the expiration scheduler re-scanning
a row it already handled, or a duplicated queue message) only ever affects
0 or 1 rows, never double-applies the inventory change. This directly
answers PRD section 12 ("the expiration process must be idempotent") and
interview question 30.
"""
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.models.enums import ReservationStatus
from src.models.reservation import InventoryReservation


def get_by_id(db: Session, reservation_id: str) -> InventoryReservation | None:
    return db.get(InventoryReservation, reservation_id)


def list_active_for_order(db: Session, order_id: str) -> list[InventoryReservation]:
    return list(
        db.execute(
            select(InventoryReservation).where(
                InventoryReservation.order_id == order_id,
                InventoryReservation.status == ReservationStatus.ACTIVE,
            )
        )
        .scalars()
        .all()
    )


def create(db: Session, reservation: InventoryReservation) -> InventoryReservation:
    db.add(reservation)
    db.flush()
    return reservation


def mark_released(db: Session, reservation_id: str) -> bool:
    """Idempotent ACTIVE -> RELEASED transition. Returns False if the
    reservation was already released/consumed by another process."""
    stmt = (
        update(InventoryReservation)
        .where(InventoryReservation.id == reservation_id, InventoryReservation.status == ReservationStatus.ACTIVE)
        .values(status=ReservationStatus.RELEASED, released_at=datetime.utcnow())
    )
    return db.execute(stmt).rowcount == 1


def mark_consumed(db: Session, reservation_id: str) -> bool:
    """Idempotent ACTIVE -> CONSUMED transition (order completed)."""
    stmt = (
        update(InventoryReservation)
        .where(InventoryReservation.id == reservation_id, InventoryReservation.status == ReservationStatus.ACTIVE)
        .values(status=ReservationStatus.CONSUMED)
    )
    return db.execute(stmt).rowcount == 1


def claim_expired_batch(db: Session, *, now: datetime, limit: int) -> list[InventoryReservation]:
    """
    Atomically claim a batch of expired reservations for release.

    A single `UPDATE ... WHERE status = 'ACTIVE' AND expires_at < :now
    RETURNING *` both selects and claims the rows in one statement, so two
    concurrent scheduler runs (or two replicas of the cleanup worker) can
    never both "claim" the same reservation: whichever transaction's UPDATE
    commits first flips the row to RELEASED, and the other's WHERE clause no
    longer matches it.
    """
    ids_subq = (
        select(InventoryReservation.id)
        .where(InventoryReservation.status == ReservationStatus.ACTIVE, InventoryReservation.expires_at < now)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    claimed_ids = [row[0] for row in db.execute(ids_subq).all()]
    if not claimed_ids:
        return []

    stmt = (
        update(InventoryReservation)
        .where(InventoryReservation.id.in_(claimed_ids))
        .values(status=ReservationStatus.RELEASED, released_at=now)
        .returning(InventoryReservation)
    )
    return list(db.execute(stmt).scalars().all())
