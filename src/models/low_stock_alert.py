"""
LowStockAlert model (Low-Stock Alerts feature add-on, PRD section 5).

One immutable row per threshold crossing -- never updated or deleted, same
append-only convention as `InventoryAuditLog`. Whether a (product,
warehouse) pair is *currently* low-stock lives on `Inventory.is_low_stock`
(see that model and `inventory_repository.try_flip_low_stock` /
`try_reset_low_stock`); this table is purely the historical record of each
time that state turned on, which is what FR-6 ("list recent alerts") reads
from.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class LowStockAlert(Base):
    __tablename__ = "low_stock_alerts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    quantity_at_alert: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
