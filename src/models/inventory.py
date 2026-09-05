"""
Inventory model — per (product, warehouse) stock levels (PRD section 5.3).

This is the single most contended table in the whole system: every order
creation, cancellation, expiration, and completion touches a row here. See
`src/services/inventory_service.py` for how concurrent access to these rows
is made safe.

Two CHECK constraints enforce the PRD's data-integrity rule
("available_quantity >= 0 and reserved_quantity >= 0. Inventory must never
become negative") directly in the database, as a last line of defense that
holds even if application code has a bug -- Postgres will reject the write
outright rather than silently corrupting stock counts.
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_inventory_product_warehouse"),
        CheckConstraint("available_quantity >= 0", name="ck_inventory_available_nonnegative"),
        CheckConstraint("reserved_quantity >= 0", name="ck_inventory_reserved_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    available_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
