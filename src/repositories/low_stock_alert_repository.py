"""Data access for the `low_stock_alerts` table (Low-Stock Alerts add-on)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.ids import generate_id
from src.models.low_stock_alert import LowStockAlert


def create(db: Session, *, product_id: str, warehouse_id: str, quantity_at_alert: int, threshold: int) -> LowStockAlert:
    """Insert one immutable alert record. Caller is responsible for calling
    this only when `inventory_repository.try_flip_low_stock` actually
    reported a crossing, so it is never invoked more than once per
    crossing (see inventory_service.py)."""
    alert = LowStockAlert(
        id=generate_id("lsa"),
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity_at_alert=quantity_at_alert,
        threshold=threshold,
    )
    db.add(alert)
    db.flush()
    return alert


def list_recent(db: Session, *, warehouse_id: str | None = None, limit: int = 100) -> list[LowStockAlert]:
    stmt = select(LowStockAlert).order_by(LowStockAlert.created_at.desc()).limit(limit)
    if warehouse_id is not None:
        stmt = stmt.where(LowStockAlert.warehouse_id == warehouse_id)
    return list(db.execute(stmt).scalars().all())
