"""
Idempotency orchestration used by `order_service.create_order` (PRD section 8).

Usage pattern in the caller:

    claim = begin(db, key, payload_dict)
    if claim.cached_response is not None:
        return claim.cached_response          # replay, no new order created
    ... create the order, build response_body ...
    complete(db, claim.entry, order_id=order.id, response_body=response_body)
    db.commit()                                # single commit for everything

Everything happens inside the caller's single transaction/commit so that if
order creation fails partway through, the idempotency claim rolls back with
it -- a failed attempt never "poisons" the key, and the client's retry with
the same key is free to succeed.
"""
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.core.exceptions import IdempotencyConflictError, InvalidRequestError
from src.models.enums import IdempotencyStatus
from src.models.idempotency import IdempotencyKey
from src.repositories import idempotency_repository


def compute_request_hash(payload: dict[str, Any]) -> str:
    """Stable hash of the request body, used to detect a key being reused
    with a different payload (a client bug we should surface, not mask)."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class IdempotencyClaim:
    entry: IdempotencyKey | None
    cached_response: dict[str, Any] | None


def begin(db: Session, key: str, payload: dict[str, Any]) -> IdempotencyClaim:
    request_hash = compute_request_hash(payload)

    entry = idempotency_repository.try_claim(db, key, request_hash)
    if entry is not None:
        return IdempotencyClaim(entry=entry, cached_response=None)

    # Someone else already holds (or held) this key. Lock the row so we see
    # its final, settled state rather than an in-flight one.
    existing = idempotency_repository.get_for_update(db, key)
    if existing is None:  # pragma: no cover - can't happen: try_claim just told us it exists
        raise InvalidRequestError("Idempotency key state is inconsistent, please retry")

    if existing.request_hash != request_hash:
        raise InvalidRequestError(
            "This Idempotency-Key was already used with a different request body",
            {"idempotency_key": key},
        )

    if existing.status == IdempotencyStatus.COMPLETED:
        return IdempotencyClaim(entry=existing, cached_response=existing.response_body)

    # Still IN_PROGRESS after we acquired the row lock: the original request
    # that owns this key rolled back without completing it (e.g. it hit an
    # unrelated error after claiming the key). Rather than silently
    # retrying on its behalf, surface a 409 so the client can safely retry
    # the whole request with a fresh key or the same one.
    raise IdempotencyConflictError(
        "A previous request with this Idempotency-Key did not complete successfully; please retry",
        {"idempotency_key": key},
    )


def complete(db: Session, entry: IdempotencyKey, *, order_id: str, response_body: dict[str, Any]) -> None:
    idempotency_repository.mark_completed(db, entry, order_id=order_id, response_body=response_body)
