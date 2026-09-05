"""Data access for the `dead_letter_orders` table (Bonus B)."""
from sqlalchemy.orm import Session

from src.core.ids import generate_id
from src.models.dead_letter import DeadLetterOrder


def record(db: Session, *, order_id: str, reason: str, attempts: int) -> DeadLetterOrder:
    entry = DeadLetterOrder(id=generate_id("dlq"), order_id=order_id, reason=reason, attempts=attempts)
    db.add(entry)
    db.flush()
    return entry
