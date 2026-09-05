"""
OutboxEvent model (Bonus C — Transactional Outbox Pattern).

Answers interview question: "What happens if your API commits an order to
PostgreSQL but crashes before publishing the queue message?"

Without an outbox, publishing to Celery/Redis after the DB commit leaves a
gap where a crash (or a Redis blip) loses the message forever, even though
the order and its reservation are safely committed. By writing the outbox
row in the *same transaction* as the order/reservation (see
`order_service.create_order`), publication becomes durable: a separate
relay process (`src/workers/outbox_relay.py`) polls for PENDING rows and
only marks them PUBLISHED after the Celery task has been enqueued
successfully. If the relay crashes mid-way, the row is simply still PENDING
next time it looks, and it re-publishes -- which is why the order worker
must itself be idempotent (see `order_processor.py`) against
being invoked more than once for the same order.
"""
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.enums import OutboxStatus


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, name="outbox_status"), nullable=False, default=OutboxStatus.PENDING, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
