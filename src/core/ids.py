"""
ID generation.

Every entity gets a prefixed, globally-unique, non-sequential identifier,
e.g. `prod_3f9c...`, `order_a1b2...`. Rationale (see README > "How IDs are
generated"):

  - UUID4 avoids the "next ID" contention/predictability problems of
    auto-increment primary keys under concurrent inserts, and means IDs can
    be generated client-side or in the service layer before the row is
    ever inserted (useful for idempotency and for the outbox pattern).
  - A human-readable prefix (matching the PRD's own examples like
    "prod_123", "order_123") makes IDs self-describing in logs, URLs, and
    support tickets without needing a lookup.
"""
import uuid


def generate_id(prefix: str) -> str:
    """Return a new prefixed unique ID, e.g. generate_id("order") -> 'order_9b1d...'."""
    return f"{prefix}_{uuid.uuid4().hex}"
