"""Data access for the `warehouses` table."""
from sqlalchemy.orm import Session

from src.models.warehouse import Warehouse


def get_by_id(db: Session, warehouse_id: str) -> Warehouse | None:
    return db.get(Warehouse, warehouse_id)


def create(db: Session, warehouse: Warehouse) -> Warehouse:
    db.add(warehouse)
    db.flush()
    return warehouse
