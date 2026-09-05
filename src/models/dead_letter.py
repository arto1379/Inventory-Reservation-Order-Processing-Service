"""
DeadLetterOrder model (Bonus B — Dead-Letter Queue).

When the order worker exhausts its retry budget (see
`workers/order_processor.py` and `PAYMENT_MAX_ATTEMPTS`), instead of the
order silently sitting in FAILED with no operational trail, a row is
written here recording the failure reason and attempt count. This gives
operators a queryable "needs investigation" list, satisfying the PRD's
"placed in a dead-letter queue for investigation" requirement without
standing up a second physical queue -- a table is enough at this scale, and
keeps the mechanism inspectable via a normal SQL query instead of requiring
a queue-browser tool.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class DeadLetterOrder(Base):
    __tablename__ = "dead_letter_orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
