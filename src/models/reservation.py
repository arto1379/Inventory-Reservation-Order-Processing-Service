"""
InventoryReservation model (PRD section 5.5).

Each row represents one line item's temporary hold on stock. `status` is an
addition beyond the PRD's literal field list (which only lists
`released_at`) so that release/consume operations can be made idempotent
with a single conditional `UPDATE ... WHERE status = 'ACTIVE'` (see
`inventory_service.release_reservation`) instead of relying solely on
`released_at IS NULL`, which reads less explicitly when reasoning about the
state machine.
"""
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.enums import ReservationStatus


class InventoryReservation(Base):
    __tablename__ = "inventory_reservations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus, name="reservation_status"),
        nullable=False,
        default=ReservationStatus.ACTIVE,
        # Composite index on (status, expires_at) is what makes the
        # reservation-cleanup scan efficient at scale (see migration).
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
