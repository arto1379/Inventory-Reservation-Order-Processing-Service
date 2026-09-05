"""
Data access for the `idempotency_keys` table.

See `src/models/idempotency.py` for the full flow explanation and
`src/services/idempotency_service.py` for how these primitives are composed.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models.enums import IdempotencyStatus
from src.models.idempotency import IdempotencyKey


def try_claim(db: Session, key: str, request_hash: str) -> IdempotencyKey | None:
    """
    Attempt to INSERT a new IN_PROGRESS row for this key.

    Returns the new row if this caller now owns the key (no prior row
    existed). Returns None if a row already exists (caller should look it
    up with `get_for_update` instead). Relies on the primary key constraint
    on `key` as the actual concurrency guard -- two threads/processes
    racing here will have exactly one INSERT succeed.

    Wrapped in a SAVEPOINT (`begin_nested`) so that on conflict only this
    INSERT is rolled back, not the rest of the caller's transaction -- this
    is meant to be called as the first step of a larger unit of work (see
    idempotency_service.py), not in isolation.
    """
    entry = IdempotencyKey(key=key, request_hash=request_hash, status=IdempotencyStatus.IN_PROGRESS)
    try:
        with db.begin_nested():
            db.add(entry)
            db.flush()
        return entry
    except IntegrityError:
        return None


def get_for_update(db: Session, key: str) -> IdempotencyKey | None:
    """
    Row-lock the existing idempotency record. If another request is still
    IN_PROGRESS for this key, this blocks until that request commits (or
    rolls back), so the caller always sees the final, settled state instead
    of racing with it.
    """
    return db.execute(select(IdempotencyKey).where(IdempotencyKey.key == key).with_for_update()).scalar_one_or_none()


def mark_completed(db: Session, entry: IdempotencyKey, *, order_id: str, response_body: dict) -> IdempotencyKey:
    entry.status = IdempotencyStatus.COMPLETED
    entry.order_id = order_id
    entry.response_body = response_body
    db.flush()
    return entry
