"""Inventory endpoints (PRD FR-3, FR-4). Both are ADMIN-only per section 16."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.api.deps import get_db, require_roles
from src.models.enums import UserRole
from src.schemas.inventory import InventoryAdjustmentRequest, InventoryAdjustmentResponse, ProductInventoryResponse
from src.services import inventory_service

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
    "/{product_id}",
    response_model=ProductInventoryResponse,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def get_inventory(product_id: str, db: Session = Depends(get_db)) -> ProductInventoryResponse:
    return inventory_service.get_inventory_for_product(db, product_id)
