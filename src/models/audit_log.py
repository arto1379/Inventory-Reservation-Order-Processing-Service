"""
InventoryAuditLog model (PRD section 15).

Immutable by convention: the codebase never contains an UPDATE or DELETE
against this table, only INSERTs (enforced by code review discipline, not a
DB trigger -- see README > "Known limitations" for the trade-off).
"""
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.enums import AuditEventType


class InventoryAuditLog(Base):
    __tablename__ = "inventory_audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    # Signed delta applied to available_quantity by this event, e.g. -2 for
    # an order that consumed 2 units, +2 for a released reservation.
    change: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[AuditEventType] = mapped_column(Enum(AuditEventType, name="audit_event_type"), nullable=False)
    # Free-form pointer to whatever caused this change (an order ID for
    # ORDER_COMPLETED, a reservation ID for RESERVATION_RELEASED, etc).
    reference_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
