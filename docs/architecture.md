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
all share the same application code and the same database. The Low-Stock
Alerts add-on introduces no new process: its crossing detection runs
inline inside the API request that changes stock, and its notification
task (`workers.notify_low_stock`) runs on the same Celery worker shown
above, dispatched by the same outbox relay via a second event type
(`LOW_STOCK_ALERT_CREATED` alongside `ORDER_RESERVED`).

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

## Request/data flow: a low-stock crossing

Piggybacks on step 2 above rather than adding a new entry point: whichever
operation just decreased `available_quantity` (reserving stock for an
order, same transaction as step 2; or a manual adjustment,
`POST /inventory/adjustments`, its own transaction) calls
`inventory_service._check_low_stock_transition` before it commits.

1. An atomic conditional `UPDATE` (`inventory_repository.try_flip_low_stock`)
   flips `is_low_stock` False -> True iff a threshold is configured and the
   new quantity is at or below it — the exact compare-and-swap technique
   from step 2, which is what makes a concurrent double-alert impossible.
   See `docs/decisions/0005-low-stock-alerts.md`.
2. If it flipped, a `low_stock_alerts` row and an `OutboxEvent`
   (`LOW_STOCK_ALERT_CREATED`) are written in that same transaction.
3. The outbox relay picks it up on its next poll exactly like
   `ORDER_RESERVED`, and dispatches `notify_low_stock_task`
   (`src/workers/low_stock_notifier.py`), which logs the event to simulate
   notifying the warehouse team.

A restock (available quantity rising back above the threshold) runs the
mirror-image `try_reset_low_stock`, with no alert or outbox event — only a
*decrease* crossing the threshold is ever alert-worthy.

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
