"""Business logic for warehouse management (PRD FR-2)."""
from sqlalchemy.orm import Session

from src.core.exceptions import WarehouseNotFoundError
from src.core.ids import generate_id
from src.models.warehouse import Warehouse
from src.repositories import warehouse_repository
from src.schemas.warehouse import WarehouseCreateRequest


def create_warehouse(db: Session, payload: WarehouseCreateRequest) -> Warehouse:
    warehouse = Warehouse(id=generate_id("wh"), name=payload.name, location=payload.location)
    warehouse_repository.create(db, warehouse)
    db.commit()
    db.refresh(warehouse)
    return warehouse


def get_warehouse_or_404(db: Session, warehouse_id: str) -> Warehouse:
    warehouse = warehouse_repository.get_by_id(db, warehouse_id)
    if warehouse is None:
        raise WarehouseNotFoundError(f"Warehouse '{warehouse_id}' was not found", {"warehouse_id": warehouse_id})
    return warehouse
