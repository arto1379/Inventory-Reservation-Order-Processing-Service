"""Data access for the `outbox_events` table (Bonus C). See src/models/outbox.py."""
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.core.ids import generate_id
from src.models.enums import OutboxStatus
from src.models.outbox import OutboxEvent


def create(db: Session, *, aggregate_type: str, aggregate_id: str, event_type: str, payload: dict) -> OutboxEvent:
    """Insert a PENDING outbox row. Caller must do this inside the same
    transaction as the business writes it describes (see order_service.py)."""
    event = OutboxEvent(
        id=generate_id("outbox"),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    db.flush()
    return event


def claim_pending_batch(db: Session, limit: int) -> list[OutboxEvent]:
    """Lock a batch of PENDING events for this relay process to publish.
    `skip_locked` lets multiple relay replicas run safely side by side."""
    return list(
        db.execute(
            select(OutboxEvent)
            .where(OutboxEvent.status == OutboxStatus.PENDING)
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )


def mark_published(db: Session, event_id: str) -> None:
    db.execute(
        update(OutboxEvent).where(OutboxEvent.id == event_id).values(status=OutboxStatus.PUBLISHED, published_at=datetime.utcnow())
    )
