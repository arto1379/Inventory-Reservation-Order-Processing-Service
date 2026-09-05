"""
IdempotencyKey model (PRD section 8).

Flow:
  1. Request arrives with an `Idempotency-Key` header.
  2. We try to INSERT a row with status=IN_PROGRESS. The primary key
     constraint on `key` means a concurrent duplicate request's INSERT will
     fail -- the database itself is the synchronization point, not
     application-level locking.
  3. If the insert succeeds, we own this key: process the order, then
     UPDATE the row to status=COMPLETED with the resulting response body.
  4. If the insert fails (key already exists), we SELECT ... FOR UPDATE the
     existing row (blocking until any in-flight request holding it
     commits), then return its stored `response_body` if COMPLETED.

See `src/services/idempotency_service.py` for the full implementation.
"""
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.enums import IdempotencyStatus


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    # SHA-256 hex digest of the request body. If a caller reuses the same
    # key with a *different* payload, we treat that as a client bug rather
    # than silently returning a mismatched cached response.
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[IdempotencyStatus] = mapped_column(
        Enum(IdempotencyStatus, name="idempotency_status"), nullable=False, default=IdempotencyStatus.IN_PROGRESS
    )
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
