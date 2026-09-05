"""Data access for the `orders` / `order_items` tables."""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.models.enums import OrderStatus
from src.models.order import Order, OrderItem


def get_by_id(db: Session, order_id: str) -> Order | None:
    """Fetch an order with its line items eager-loaded in one query (avoids
    an N+1 lazy-load when serializing the response)."""
    return db.execute(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    ).scalar_one_or_none()


def get_by_id_for_update(db: Session, order_id: str) -> Order | None:
    """
    Row-lock the order for the duration of the current transaction.

    Used by cancellation and by the order worker so that "cancel this
    order" and "the worker is processing this order" can never both act on
    it at the same time -- whichever transaction gets there first wins the
    lock, and the second one sees the already-updated status once it
    proceeds (see order_service.cancel_order and workers/order_processor.py).
    """
    return db.execute(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items)).with_for_update()
    ).scalar_one_or_none()


def get_by_idempotency_key(db: Session, key: str) -> Order | None:
    return db.execute(select(Order).where(Order.idempotency_key == key)).scalar_one_or_none()


def create(db: Session, order: Order, items: list[OrderItem]) -> Order:
    db.add(order)
    db.add_all(items)
    db.flush()
    return order


def update_status(db: Session, order: Order, status: OrderStatus) -> Order:
    order.status = status
    db.flush()
    return order


def list_orders(
    db: Session,
    *,
    status: OrderStatus | None,
    created_after: datetime | None,
    created_before: datetime | None,
    user_id_filter: str | None,
    page: int,
    limit: int,
) -> tuple[list[Order], int]:
    """
    Returns (orders_page, total_count). `user_id_filter` scopes results to
    one owner's orders (used to enforce that CLIENT users only ever see
    their own orders -- ADMIN callers pass `None`).
    """
    stmt = select(Order)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if created_after is not None:
        stmt = stmt.where(Order.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(Order.created_at <= created_before)
    if user_id_filter is not None:
        stmt = stmt.where(Order.created_by_user_id == user_id_filter)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    stmt = (
        stmt.options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    orders = list(db.execute(stmt).scalars().all())
    return orders, total
