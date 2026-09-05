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

`low_stock_threshold` / `is_low_stock` are the Low-Stock Alerts add-on
(PRD section 5): stored directly on this row rather than a separate table,
since they describe *this specific* (product, warehouse) pair and every
write that needs to inspect/flip them is already touching this row. See
`inventory_repository.try_flip_low_stock` / `try_reset_low_stock` for how
`is_low_stock` is flipped atomically to avoid duplicate alerts under
concurrent stock changes, and `docs/decisions/0005-low-stock-alerts.md` for
the full write-up.
"""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_inventory_product_warehouse"),
        CheckConstraint("available_quantity >= 0", name="ck_inventory_available_nonnegative"),
        CheckConstraint("reserved_quantity >= 0", name="ck_inventory_reserved_nonnegative"),
        CheckConstraint(
            "low_stock_threshold IS NULL OR low_stock_threshold >= 0",
            name="ck_inventory_low_stock_threshold_nonnegative",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    available_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # NULL threshold means the admin hasn't configured alerting for this
    # pair yet (see low_stock_service.set_threshold).
    low_stock_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_low_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
