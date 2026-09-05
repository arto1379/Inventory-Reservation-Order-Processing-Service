"""
Order endpoints (PRD FR-5, sections 8, 13, 14).

Creation and cancellation are CLIENT actions; both roles can read orders,
scoped by ownership for CLIENT users (see order_service._authorize_view /
list_orders).
"""
import math
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session

from src.api.deps import get_db, require_roles
from src.models.enums import OrderStatus, UserRole
from src.models.user import User
from src.schemas.common import PaginationMeta
from src.schemas.order import OrderCreateRequest, OrderListResponse, OrderResponse
from src.services import order_service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.CLIENT)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    """
    Validates products, reserves inventory, creates the order, and records
    an outbox event for asynchronous processing -- all in one transaction
    (see order_service.create_order for the full breakdown). Supports the
    optional `Idempotency-Key` header (PRD section 8): replaying the same
    key returns the original order instead of creating a duplicate.
    """
    return order_service.create_order(db, payload, current_user, idempotency_key)


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.CLIENT)),
) -> OrderResponse:
    order = order_service.get_order_or_404(db, order_id, current_user)
    return OrderResponse.model_validate(order)


@router.get("", response_model=OrderListResponse)
def list_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.CLIENT)),
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> OrderListResponse:
    result = order_service.list_orders(
        db,
        current_user=current_user,
        status=status_filter,
        created_after=created_after,
        created_before=created_before,
        page=page,
        limit=limit,
    )
    total_pages = math.ceil(result.total / limit) if result.total else 0
    return OrderListResponse(
        orders=[OrderResponse.model_validate(o) for o in result.orders],
        pagination=PaginationMeta(page=page, limit=limit, total=result.total, total_pages=total_pages),
    )


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.CLIENT)),
) -> OrderResponse:
    order = order_service.cancel_order(db, order_id, current_user)
    return OrderResponse.model_validate(order)
