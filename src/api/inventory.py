"""
Inventory endpoints (PRD FR-3, FR-4) plus the Low-Stock Alerts add-on
(FR-1, FR-6). All ADMIN-only per section 16.

Route ordering note: `/low-stock` (a fixed segment) is registered before
`/{product_id}` (a single-segment path parameter) further down, since
FastAPI/Starlette matches routes in registration order and `/{product_id}`
would otherwise swallow `GET /inventory/low-stock` by capturing "low-stock"
as a product_id.
"""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.api.deps import get_db, require_roles
from src.models.enums import UserRole
from src.schemas.inventory import InventoryAdjustmentRequest, InventoryAdjustmentResponse, ProductInventoryResponse
from src.schemas.low_stock import (
    LowStockAlertListResponse,
    LowStockAlertResponse,
    LowStockThresholdRequest,
    LowStockThresholdResponse,
)
from src.services import inventory_service, low_stock_service

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.post(
    "/adjustments",
    response_model=InventoryAdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def create_adjustment(payload: InventoryAdjustmentRequest, db: Session = Depends(get_db)) -> InventoryAdjustmentResponse:
    """Add or remove stock (e.g. a warehouse delivery). Always generates an
    immutable audit record in the same transaction as the stock change."""
    row = inventory_service.create_adjustment(db, payload)
    return InventoryAdjustmentResponse(
        product_id=row.product_id,
        warehouse_id=row.warehouse_id,
        available_quantity=row.available_quantity,
        reserved_quantity=row.reserved_quantity,
    )


@router.get(
    "/low-stock",
    response_model=LowStockAlertListResponse,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def list_low_stock_alerts(
    warehouse_id: str | None = Query(default=None), db: Session = Depends(get_db)
) -> LowStockAlertListResponse:
    """List recent low-stock alerts (FR-6), optionally scoped to one warehouse."""
    alerts = low_stock_service.list_alerts(db, warehouse_id=warehouse_id)
    return LowStockAlertListResponse(alerts=[LowStockAlertResponse.model_validate(a) for a in alerts])


@router.put(
    "/{product_id}/warehouses/{warehouse_id}/low-stock-threshold",
    response_model=LowStockThresholdResponse,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def set_low_stock_threshold(
    product_id: str, warehouse_id: str, payload: LowStockThresholdRequest, db: Session = Depends(get_db)
) -> LowStockThresholdResponse:
    """Set or update a product/warehouse pair's low-stock threshold (FR-1)."""
    row = low_stock_service.set_threshold(db, product_id, warehouse_id, payload.threshold)
    return LowStockThresholdResponse(
        product_id=row.product_id,
        warehouse_id=row.warehouse_id,
        threshold=row.low_stock_threshold,
        is_low_stock=row.is_low_stock,
    )


@router.get(
    "/{product_id}",
    response_model=ProductInventoryResponse,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def get_inventory(product_id: str, db: Session = Depends(get_db)) -> ProductInventoryResponse:
    return inventory_service.get_inventory_for_product(db, product_id)
