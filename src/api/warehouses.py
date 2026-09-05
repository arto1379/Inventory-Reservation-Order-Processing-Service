"""Warehouse endpoints (PRD FR-2). ADMIN-only per section 16."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.api.deps import get_db, require_roles
from src.models.enums import UserRole
from src.schemas.warehouse import WarehouseCreateRequest, WarehouseResponse
from src.services import warehouse_service

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


@router.post(
    "",
    response_model=WarehouseResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def create_warehouse(payload: WarehouseCreateRequest, db: Session = Depends(get_db)) -> WarehouseResponse:
    warehouse = warehouse_service.create_warehouse(db, payload)
    return WarehouseResponse.model_validate(warehouse)
