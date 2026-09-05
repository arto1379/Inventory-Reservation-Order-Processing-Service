"""
Order and OrderItem models (PRD section 5.4).

`payment_token` is a deliberate addition beyond the PRD's literal schema: it
lets callers deterministically choose the simulated payment outcome for a
given order (PRD section 10 defines the "success" / "fail" tokens but the
PRD's example request body has no field to carry one). Defaults to
"success" so callers that don't care about testing failure paths don't need
to know it exists.
"""
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.models.enums import OrderStatus


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"), nullable=False, default=OrderStatus.PENDING, index=True
    )
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    # Owning client (see RBAC rules: CLIENT users can only see/cancel their
    # own orders; ADMIN users can see all of them).
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    # Simulated payment outcome selector — see module docstring.
    payment_token: Mapped[str] = mapped_column(String(32), nullable=False, default="success")

    # Number of processing attempts made by the order worker so far. Used to
    # drive the retry-with-backoff policy (Bonus A) and the dead-letter
    # threshold (Bonus B).
    processing_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Populated only when the client supplied an Idempotency-Key header.
    # The unique index lets the DB itself guarantee two concurrent requests
    # with the same key can never both create an order (see
    # idempotency_service.py for the full flow).
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped["Order"] = relationship("Order", back_populates="items")
