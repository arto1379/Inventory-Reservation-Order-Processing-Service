# 0002 — Idempotency-Key implementation

## Context

PRD section 8: repeating an order-creation request with the same
`Idempotency-Key` must return the original order, not create a duplicate,
even if the two requests race each other.

## Decision

A dedicated `idempotency_keys` table (`key` PRIMARY KEY,
`request_hash`, `status`, `response_body` JSONB) plus a claim protocol
implemented in `src/services/idempotency_service.py` and
`src/repositories/idempotency_repository.py`:

1. **Claim**: `INSERT` a row with `status = IN_PROGRESS`, wrapped in a
   `SAVEPOINT` (`Session.begin_nested()`). Two concurrent requests with the
   same key race on the table's primary-key constraint — the database
   itself is the synchronization point, not application-level locking.
2. **Loser path**: the request that lost the `INSERT` race runs
   `SELECT ... FOR UPDATE` on the existing row. This *blocks* until the
   winner's transaction commits or rolls back, so the loser never has to
   poll or guess — it simply waits for the final, settled state:
   - `COMPLETED` → return the stored `response_body` (the original order),
     no new order created.
   - a different `request_hash` → `400 INVALID_REQUEST` (the key was
     reused for a materially different request — a client bug worth
     surfacing, not masking).
   - still `IN_PROGRESS` after the lock is granted → the original request
     must have rolled back without completing (e.g. it failed validation
     after claiming the key); return `409 IDEMPOTENCY_KEY_IN_PROGRESS` so
     the caller can safely retry.
3. **Completion**: the claim, the order/reservation inserts, and the
   `UPDATE idempotency_keys SET status = COMPLETED, response_body = ...`
   all happen in **one transaction** with the winner's `db.commit()`.

## Why one transaction matters

If claiming the key were committed separately from creating the order, a
failure between the two would permanently "poison" the key: a retry would
see `IN_PROGRESS` forever (or a stale claim) even though no order was ever
created. By keeping everything in one transaction, a failed attempt rolls
back the key claim along with it — the client's retry with the same key is
free to succeed once the underlying problem (e.g. insufficient inventory)
is resolved.

## Why hash the request body

Storing a SHA-256 hash of the normalized (post-validation) request payload
lets a key-reuse-with-different-payload bug be caught explicitly instead of
silently returning a response that doesn't match what the caller just
asked for — the same principle Stripe's and other payment APIs'
idempotency keys follow.

## Expiry

`idempotency_keys` rows are not actively purged by this implementation
(see README "Known limitations" — this is the one deliberate gap). In
production this would be a Celery Beat task deleting rows older than a
retention window (e.g. 24-48 hours, matching how long a client might
reasonably retry a request), analogous to `reservation_cleanup.py`.
