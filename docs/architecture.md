# Architecture

## Component overview

```
                          +------------------+
                          |     Client       |
                          +--------+---------+
                                   |
                                   v
                          +------------------+
                          |   FastAPI (API)  |  <-- JWT auth, validation,
                          +--------+---------+      RBAC, error envelope
                                   |
                 +-----------------+------------------+
                 |                                     |
                 v                                     v
        +-----------------+                  +------------------+
        |   PostgreSQL     |<-----------------+  Outbox Relay    |
        |  (single source  |   polls outbox_  |  (poll + publish)|
        |   of truth)      |   events table   +--------+---------+
        +--------+---------+                           |
                 ^                                      v
                 |                             +------------------+
                 |                             |   Redis (broker) |
                 |                             +--------+---------+
                 |                                      |
                 |                             +--------v---------+
                 +-----------------------------+  Celery Worker   |
                 |                             |  (order_processor)|
                 |                             +------------------+
                 |
                 |                             +------------------+
                 +-----------------------------+  Celery Beat     |
                                               |  (reservation_   |
                                               |   cleanup, every |
                                               |   60s)           |
                                               +------------------+
```

A modular monolith, per the PRD's explicit guidance ("do not over-engineer
into many microservices"): one FastAPI process, one PostgreSQL database,
one Redis instance used as both the Celery broker and result backend, and
three background processes (Celery worker, Celery beat, outbox relay) that
all share the same application code and the same database.

## Request/data flow: creating an order

1. `POST /api/v1/orders` hits `src/api/orders.py`, which authenticates the
   caller (JWT -> `CLIENT` role required) and delegates to
   `order_service.create_order`.
2. `create_order` runs entirely inside **one PostgreSQL transaction**:
   - Claims the `Idempotency-Key` (if provided) — see
     `docs/decisions/0002-idempotency.md`.
   - Validates every product ID exists.
   - For each line item, picks a warehouse and atomically reserves stock
     with a single conditional `UPDATE` — see
     `docs/decisions/0001-concurrency-strategy.md`. Any failure here rolls
     back the *entire* transaction, so an order is never left partially
     reserved.
   - Inserts the `Order`, `OrderItem`s, `InventoryReservation`s, and an
     `OutboxEvent` row (`ORDER_RESERVED`).
   - Commits once, atomically.
3. The order is returned to the client already in `RESERVED` status — the
   client does not wait for payment simulation or async processing.
4. Independently, the **outbox relay** process polls `outbox_events` for
   `PENDING` rows and calls `process_order_task.delay(order_id)`, then
   marks the row `PUBLISHED`. See `docs/decisions/0003-outbox-pattern.md`.
5. The **Celery worker** picks up the task, locks the order row, simulates
   payment (`src/services/payment_service.py`), and finalizes the order:
   `COMPLETED` (reservation consumed) or `FAILED` (reservation released),
   with retry-with-backoff for a simulated transient failure (Bonus A).
6. Independently, **Celery Beat** runs `expire_reservations` every
   `RESERVATION_CLEANUP_INTERVAL_SECONDS` to release any reservation whose
   `expires_at` has passed and mark its order `EXPIRED`.

## Layering

```
api/            <- HTTP concerns only: request parsing, auth, status codes
services/       <- business rules, transaction boundaries, orchestration
repositories/   <- SQL only: one function per query/mutation, no business logic
models/         <- SQLAlchemy ORM table definitions
schemas/        <- Pydantic request/response contracts
workers/        <- Celery tasks + the outbox relay, built on the same services
core/           <- cross-cutting: ID generation, JWT/password hashing, exceptions
middleware/     <- request-ID correlation, global error-envelope handler
```

`api/` never talks to `repositories/` directly, and `repositories/` never
raises `AppError` subclasses (those are a `services/`-and-up concept) or
knows about HTTP. This keeps the domain logic testable without spinning up
FastAPI at all (see `tests/unit/`), and keeps the Celery workers able to
reuse the exact same `services/` functions the API uses instead of
duplicating business rules.

## Why synchronous, not `async def`

Every DB-touching function in this codebase is synchronous (`Session`, not
`AsyncSession`). See `src/database.py`'s docstring for the full reasoning;
in short: the interesting engineering problem here is *transaction and
locking correctness*, not raw I/O concurrency, and synchronous SQLAlchemy
makes transaction boundaries trivial to read top-to-bottom. FastAPI still
serves concurrent requests fine — sync `def` path functions are dispatched
to a thread pool automatically — and Celery itself is synchronous, so the
API and the workers share one mental model of "a session, a transaction, a
commit" instead of running two different stacks side by side.
