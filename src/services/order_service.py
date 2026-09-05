"""
Order lifecycle business logic: creation (FR-5), retrieval/listing
(section 14), and cancellation (section 13).

`create_order` is the most important function in the whole codebase -- it
is where PRD section 7's concurrency guarantee, section 8's idempotency
guarantee, and Bonus C's outbox pattern all come together in a single
database transaction. Read the inline comments below in order; they walk
through *why* each step happens where it does, not just what it does.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from src.config import settings
from src.core.exceptions import (
    ForbiddenError,
    InsufficientInventoryError,
    OrderCannotBeCancelledError,
    OrderNotFoundError,
    ProductNotFoundError,
)
from src.core.ids import generate_id
from src.logging_config import log_event
from src.models.enums import CANCELLABLE_ORDER_STATUSES, OrderStatus, UserRole
from src.models.order import Order, OrderItem
from src.models.reservation import InventoryReservation
from src.models.user import User
from src.repositories import (
    inventory_repository,
    order_repository,
    outbox_repository,
    product_repository,
    reservation_repository,
)
from src.schemas.order import OrderCreateRequest, OrderItemResponse, OrderResponse
from src.services import idempotency_service, inventory_service

logger = logging.getLogger(__name__)


def create_order(db: Session, payload: OrderCreateRequest, current_user: User, idempotency_key: str | None) -> dict[str, Any]:
    """Validate, reserve, and create an order in one transaction. See the
    module docstring. Any failure rolls back everything -- an order is
    never left half-reserved."""
    try:
        return _create_order_impl(db, payload, current_user, idempotency_key)
    except Exception:
        db.rollback()
        raise


def _create_order_impl(
    db: Session, payload: OrderCreateRequest, current_user: User, idempotency_key: str | None
) -> dict[str, Any]:
    # --- Step 0: idempotency -------------------------------------------------
    # Claiming the key (or discovering a cached response) happens FIRST and
    # in the SAME transaction as everything below, so a claim that is never
    # completed (because order creation fails) rolls back together with it.
    claim = None
    if idempotency_key:
        claim = idempotency_service.begin(db, idempotency_key, payload.model_dump(mode="json"))
        if claim.cached_response is not None:
            db.commit()  # release the row lock taken by idempotency_service.begin
            return claim.cached_response

    # --- Step 1: validate all products exist ---------------------------------
    product_ids = [item.product_id for item in payload.items]
    products = product_repository.get_many_by_ids(db, product_ids)
    missing_ids = [pid for pid in product_ids if pid not in products]
    if missing_ids:
        raise ProductNotFoundError(
            f"Product(s) not found: {', '.join(missing_ids)}", {"product_ids": missing_ids}
        )

    # --- Step 2: pick a warehouse per line item and reserve atomically -------
    # Each `inventory_service.reserve` call is a single conditional UPDATE
    # (see inventory_repository.try_reserve). If item 2 of 3 fails here, the
    # exception propagates up to `create_order`'s try/except, which rolls
    # back the whole transaction -- including item 1's already-applied
    # reservation. This is what makes "reserve everything or nothing" true
    # without needing to manually undo earlier steps.
    order_id = generate_id("order")
    order_items: list[OrderItem] = []
    reservations: list[InventoryReservation] = []
    total = Decimal("0")
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.reservation_timeout_minutes)

    for line in payload.items:
        product = products[line.product_id]
        best_warehouse = inventory_repository.find_best_warehouse(db, line.product_id, line.quantity)
        if best_warehouse is None:
            _raise_insufficient_inventory(db, line.product_id, line.quantity)

        reserved = inventory_service.reserve(
            db,
            product_id=line.product_id,
            warehouse_id=best_warehouse.warehouse_id,
            quantity=line.quantity,
            order_id=order_id,
        )
        if not reserved:
            # Someone else reserved the remaining stock between our SELECT
            # (find_best_warehouse) and our UPDATE (reserve) -- a real but
            # narrow race. Reporting insufficient inventory here is correct
            # and safe: nothing has been committed yet.
            _raise_insufficient_inventory(db, line.product_id, line.quantity)

        unit_price = Decimal(str(product.price))
        total += unit_price * line.quantity
        order_items.append(
            OrderItem(
                id=generate_id("item"),
                order_id=order_id,
                product_id=line.product_id,
                warehouse_id=best_warehouse.warehouse_id,
                quantity=line.quantity,
                unit_price=unit_price,
            )
        )
        reservations.append(
            InventoryReservation(
                id=generate_id("resv"),
                order_id=order_id,
                product_id=line.product_id,
                warehouse_id=best_warehouse.warehouse_id,
                quantity=line.quantity,
                expires_at=expires_at,
            )
        )

    # --- Step 3: create the order (already RESERVED -- reservation above
    # already succeeded for every line item at this point) -------------------
    order = Order(
        id=order_id,
        status=OrderStatus.RESERVED,
        total=total,
        created_by_user_id=current_user.id,
        payment_token=payload.payment_token,
        idempotency_key=idempotency_key,
    )
    order_repository.create(db, order, order_items)
    for reservation in reservations:
        reservation_repository.create(db, reservation)

    # --- Step 4: transactional outbox (Bonus C) ------------------------------
    # Written in the SAME transaction/commit as the order + reservations
    # above. A separate relay process (workers/outbox_relay.py) publishes
    # this row to Celery *after* this transaction commits, so a crash
    # between "commit" and "enqueue" can never lose the message -- the row
    # is simply still PENDING and gets picked up on the next poll.
    outbox_repository.create(
        db,
        aggregate_type="order",
        aggregate_id=order_id,
        event_type="ORDER_RESERVED",
        payload={"order_id": order_id},
    )

    db.flush()
    db.refresh(order)  # populate server-generated created_at/updated_at
    response_body = _serialize_order(order, order_items)

    if claim is not None:
        idempotency_service.complete(db, claim.entry, order_id=order_id, response_body=response_body)

    db.commit()
    log_event(logger, logging.INFO, "order_created", order_id=order_id, item_count=len(order_items), total=str(total))
    return response_body


def _raise_insufficient_inventory(db: Session, product_id: str, requested: int) -> None:
    available = inventory_repository.total_available(db, product_id)
    raise InsufficientInventoryError(
        f"Not enough inventory is available for product {product_id}",
        {"requested": requested, "available": available},
    )


def _serialize_order(order: Order, items: list[OrderItem]) -> dict[str, Any]:
    return OrderResponse(
        id=order.id,
        status=order.status,
        total=float(order.total),
        items=[
            OrderItemResponse(product_id=i.product_id, quantity=i.quantity, unit_price=float(i.unit_price))
            for i in items
        ],
        created_at=order.created_at,
        updated_at=order.updated_at,
    ).model_dump(mode="json")


def get_order_or_404(db: Session, order_id: str, current_user: User) -> Order:
    order = order_repository.get_by_id(db, order_id)
    if order is None:
        raise OrderNotFoundError(f"Order '{order_id}' was not found", {"order_id": order_id})
    _authorize_view(order, current_user)
    return order


def _authorize_view(order: Order, current_user: User) -> None:
    if current_user.role == UserRole.CLIENT and order.created_by_user_id != current_user.id:
        raise ForbiddenError("You do not have access to this order")


@dataclass
class OrderPage:
    orders: list[Order]
    total: int


def list_orders(
    db: Session,
    *,
    current_user: User,
    status: OrderStatus | None,
    created_after: datetime | None,
    created_before: datetime | None,
    page: int,
    limit: int,
) -> OrderPage:
    # CLIENT users only ever see their own orders; ADMIN users see everyone's
    # (PRD section 16: CLIENT can "Retrieve orders", ADMIN can "View orders").
    user_id_filter = None if current_user.role == UserRole.ADMIN else current_user.id
    orders, total = order_repository.list_orders(
        db,
        status=status,
        created_after=created_after,
        created_before=created_before,
        user_id_filter=user_id_filter,
        page=page,
        limit=limit,
    )
    return OrderPage(orders=orders, total=total)


def cancel_order(db: Session, order_id: str, current_user: User) -> Order:
    """
    Cancel an order (PRD section 13). Allowed only from PENDING/RESERVED.

    The order row is locked with `SELECT ... FOR UPDATE` for the whole
    operation so a cancellation can never race with the order worker
    concurrently moving the same order into PROCESSING/COMPLETED -- whoever
    acquires the lock first "wins", and the loser's status check (against
    the now up-to-date row) correctly rejects the cancellation if the order
    already moved past RESERVED.
    """
    try:
        order = order_repository.get_by_id_for_update(db, order_id)
        if order is None:
            raise OrderNotFoundError(f"Order '{order_id}' was not found", {"order_id": order_id})

        if current_user.role == UserRole.CLIENT and order.created_by_user_id != current_user.id:
            raise ForbiddenError("You do not have access to this order")

        if order.status not in CANCELLABLE_ORDER_STATUSES:
            raise OrderCannotBeCancelledError(
                f"Order '{order_id}' cannot be cancelled from status {order.status.value}",
                {"order_id": order_id, "status": order.status.value},
            )

        active_reservations = reservation_repository.list_active_for_order(db, order_id)
        for reservation in active_reservations:
            inventory_service.release_reservation(db, reservation, reference_id=order_id)

        order_repository.update_status(db, order, OrderStatus.CANCELLED)
        db.commit()
        db.refresh(order)
        log_event(logger, logging.INFO, "order_cancelled", order_id=order_id)
        return order
    except Exception:
        db.rollback()
        raise
