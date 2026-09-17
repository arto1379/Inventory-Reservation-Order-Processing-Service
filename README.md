# Inventory Reservation & Order Processing Service

A backend service for an e-commerce company with multiple warehouses:
manage products/inventory, reserve stock safely under concurrent demand,
process orders asynchronously with simulated payments, and keep a full
audit trail of every inventory change.

Built with **Python 3.12, FastAPI, PostgreSQL (SQLAlchemy 2.0 + Alembic),
Celery + Redis**, and JWT authentication.

## Table of contents

- [Architecture](#architecture)
- [How to run the application](#how-to-run-the-application)
- [How to run tests](#how-to-run-tests)
- [Trying the API](#trying-the-api)
- [API documentation](#api-documentation)
- [Database design](#database-design)
- [How inventory concurrency is handled](#how-inventory-concurrency-is-handled)
- [How idempotency is implemented](#how-idempotency-is-implemented)
- [Order lifecycle](#order-lifecycle)
- [Low-stock alerts](#low-stock-alerts)
- [Authentication & authorization](#authentication--authorization)
- [Configuration](#configuration)
- [Important architectural decisions](#important-architectural-decisions)
- [Bonus features implemented](#bonus-features-implemented)
- [Known limitations](#known-limitations)
- [What I'd improve with more time](#what-id-improve-with-more-time)
- [License](#license)

## Architecture

```
Client -> FastAPI (REST API) -> PostgreSQL (source of truth)
                              -> outbox_events table -> Outbox Relay -> Redis -> Celery Worker (order processing)
                                                                               -> Celery Beat  (reservation expiry, every 60s)
```

A single modular monolith plus background workers, as the PRD asks for —
not a microservices split. See **[docs/architecture.md](docs/architecture.md)**
for the full component diagram, request-flow walkthrough, and layering
rules (`api/` → `services/` → `repositories/` → `models/`).

Project layout:

```
src/
├── api/            HTTP layer: routers, auth dependency, RBAC
├── services/       business logic + transaction boundaries
├── repositories/   raw SQL/ORM queries, no business rules
├── models/         SQLAlchemy tables
├── schemas/        Pydantic request/response contracts
├── workers/        Celery tasks, beat schedule, outbox relay
├── middleware/      request-ID correlation, global error handler
├── core/           IDs, JWT/password hashing, exception hierarchy
├── config.py       environment-driven settings (pydantic-settings)
├── database.py     SQLAlchemy engine/session
├── main.py         FastAPI app assembly
└── bootstrap.py    creates the default admin user on first startup
migrations/         Alembic migrations
tests/
├── unit/           pure logic, no HTTP layer
├── integration/    full API + worker flows against a real Postgres
└── concurrency/    the PRD-required 100-simultaneous-requests test
docs/
├── architecture.md
└── decisions/      one file per major engineering decision
```

## How to run the application

**Prerequisites:** Docker + Docker Compose.

```bash
git clone <repository>
cd <repository>
cp .env.example .env      # customize if you like; sane defaults work as-is
docker compose up --build
```

This starts PostgreSQL, Redis, the API, the Celery worker, Celery Beat, and
the outbox relay. On first boot the `api` service automatically:

1. Runs `alembic upgrade head` (applies all migrations).
2. Runs `python -m src.bootstrap`, which creates a default **ADMIN** user
   from `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` in `.env` (skipped
   if it already exists) — so you have a working admin login with zero
   manual setup.
3. Starts `uvicorn` on `http://localhost:8000`.

Check it's healthy:

```bash
curl http://localhost:8000/health
# {"status": "healthy", "database": "connected", "queue": "connected"}
```

Interactive API docs: **http://localhost:8000/docs**

### Running without Docker (local Python)

```bash
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env   # point DATABASE_URL/REDIS_URL at your local Postgres/Redis
alembic upgrade head
python -m src.bootstrap
uvicorn src.main:app --reload            # terminal 1: API
celery -A src.workers.celery_app worker --loglevel=info    # terminal 2
celery -A src.workers.celery_app beat --loglevel=info      # terminal 3
python -m src.workers.outbox_relay                          # terminal 4
```

## How to run tests

Tests run against a **real PostgreSQL database** (not SQLite/mocks) — the
whole point of this project is database-level concurrency and locking
behavior, which SQLite cannot faithfully reproduce.

```bash
docker compose up -d postgres     # only Postgres is needed; tests don't need Redis/Celery
pip install -r requirements.txt
pytest                             # runs unit + integration + concurrency tests
pytest --cov=src                   # with coverage
pytest tests/concurrency -v        # just the required 100-request concurrency test
```

Tests connect to `TEST_DATABASE_URL` (default:
`postgresql+psycopg2://postgres:postgres@localhost:5432/inventory_db_test`,
auto-created by `scripts/init-test-db.sql` the first time the `postgres`
container initializes its data directory). Schema is created directly from
the SQLAlchemy models (`Base.metadata.create_all`) so tests don't depend on
migration history; every table is truncated between tests for isolation.
Celery runs in **eager mode** during tests (no broker needed) — see
`tests/conftest.py`.

What's covered:

| Test file | What it proves |
|---|---|
| `tests/unit/test_inventory_service.py` | Reserve/release/consume/adjust primitives, including "never goes negative" |
| `tests/unit/test_payment_service.py` | Deterministic simulated payment outcomes |
| `tests/unit/test_idempotency_hash.py` | Request-hash stability (order-independent, payload-sensitive) |
| `tests/integration/test_products_api.py` | FR-1, duplicate SKU, RBAC, auth |
| `tests/integration/test_orders_api.py` | Order creation, insufficient inventory, idempotency replay + conflict, RBAC ownership, cancellation, pagination/filtering |
| `tests/integration/test_order_processing.py` | Success/failure/retry-exhaustion/dead-letter, duplicate-delivery idempotency |
| `tests/integration/test_reservation_expiration.py` | Auto-expiry, idempotent re-run, doesn't clobber already-cancelled orders |
| `tests/integration/test_outbox_relay.py` | Outbox row written transactionally, relay publishes + triggers processing |
| `tests/integration/test_full_flow.py` | The end-to-end flow from PRD section 24, plus audit trail |
| `tests/concurrency/test_concurrent_reservation.py` | **The required PRD section 25 test**: 10 units, 100 simultaneous requests, exactly 10 succeed, 90 fail, final inventory = 0, never negative |
| `tests/unit/test_low_stock_service.py` | Low-stock threshold configuration, crossing/no-alert/reset/re-alert state transitions (add-on required tests 1-6) |
| `tests/integration/test_low_stock_api.py` | Threshold endpoint validation/RBAC/404s, alert listing + warehouse filter |
| `tests/integration/test_low_stock_notification.py` | Crossing writes a pending outbox event; relay publishes it and the notifier logs it |
| `tests/concurrency/test_concurrent_low_stock_alerts.py` | **Add-on required test 7**: 10 units, threshold 5, 100 simultaneous requests, exactly one alert created for the single crossing |

## Trying the API

```bash
# 1. Log in as the bootstrap admin
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"ChangeMe123!"}' | jq -r .access_token)

# 2. Create a product
PRODUCT=$(curl -s -X POST localhost:8000/api/v1/products \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"sku":"GPU-RTX5090","name":"RTX 5090","price":2499.99}')
PRODUCT_ID=$(echo $PRODUCT | jq -r .id)

# 3. Create a warehouse
WAREHOUSE=$(curl -s -X POST localhost:8000/api/v1/warehouses \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Vancouver Warehouse","location":"Vancouver, BC"}')
WAREHOUSE_ID=$(echo $WAREHOUSE | jq -r .id)

# 4. Add stock
curl -s -X POST localhost:8000/api/v1/inventory/adjustments \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"product_id\":\"$PRODUCT_ID\",\"warehouse_id\":\"$WAREHOUSE_ID\",\"quantity\":2,\"reason\":\"warehouse_delivery\"}"

# 5. Register + log in as a CLIENT to place an order
curl -s -X POST localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"shopper@example.com","password":"password123","role":"CLIENT"}'
CLIENT_TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"shopper@example.com","password":"password123"}' | jq -r .access_token)

# 6. Create an order (reserves inventory synchronously; payment happens async)
curl -s -X POST localhost:8000/api/v1/orders \
  -H "Authorization: Bearer $CLIENT_TOKEN" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"items\":[{\"product_id\":\"$PRODUCT_ID\",\"quantity\":1}]}"
# -> status "RESERVED" immediately; poll GET /orders/{id} to see it become COMPLETED
```

Force a deterministic **failure** or **retry** for testing, by setting
`payment_token` on order creation (see [Order lifecycle](#order-lifecycle)):
`"success"` (default), `"fail"` (permanent decline), `"fail_retryable"`
(retries with backoff, then permanently fails after
`PAYMENT_MAX_ATTEMPTS`).

## API documentation

Auto-generated OpenAPI docs, always in sync with the code (every
endpoint's request/response schema, status codes, and auth requirement
comes straight from the FastAPI route + Pydantic model definitions):

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Raw OpenAPI JSON: `http://localhost:8000/openapi.json`

To call a protected endpoint from Swagger UI: `POST /api/v1/auth/login`,
copy the `access_token`, click **Authorize**, paste it in as a Bearer
token.

## Database design

PostgreSQL, managed with Alembic (`migrations/versions/0001_initial_schema.py`).

| Table | Purpose | Key constraints |
|---|---|---|
| `users` | login + RBAC role | unique `email` |
| `products` | catalog | unique `sku` |
| `warehouses` | stocking locations | — |
| `inventory` | per (product, warehouse) stock | unique `(product_id, warehouse_id)`; `CHECK (available_quantity >= 0)`; `CHECK (reserved_quantity >= 0)` |
| `orders` | order header + status | unique `idempotency_key` (nullable) |
| `order_items` | order line items | FK to `orders`, `products`, `warehouses` |
| `inventory_reservations` | temporary stock holds | FK to `orders`; indexed on `(status, expires_at)` for the expiry scan |
| `inventory_audit_logs` | immutable change log | append-only by convention |
| `idempotency_keys` | idempotent order creation | PK `key` |
| `outbox_events` | transactional outbox (Bonus C) | indexed on `status` for relay polling |
| `dead_letter_orders` | repeatedly-failed orders (Bonus B) | FK to `orders` |
| `low_stock_alerts` | one row per threshold crossing (Low-Stock Alerts add-on) | FK to `products`, `warehouses`; indexed on `(warehouse_id, created_at)` for FR-6 listing |

`inventory` also carries `low_stock_threshold` (nullable — unset means no
alerting configured for that pair) and `is_low_stock` (current alert
state), added by the Low-Stock Alerts add-on; `CHECK (low_stock_threshold
IS NULL OR low_stock_threshold >= 0)` mirrors the same
last-line-of-defense philosophy as the two constraints above it.

**Indexes** beyond the constraints above: `orders(status)`,
`orders(created_at)`, `orders(created_by_user_id)` (list/filter/RBAC-scope
orders without a table scan); `inventory_reservations(status)` and
`inventory_reservations(expires_at)` (the expiry scheduler's exact query
shape); `inventory_audit_logs(product_id)`/`(created_at)` (audit lookups);
`products(sku)` and `users(email)` (both also unique, so this is the same
index enforcing the constraint).

## How inventory concurrency is handled

**Atomic conditional `UPDATE`** (a compare-and-swap), not
`SELECT ... FOR UPDATE`:

```sql
UPDATE inventory
SET available_quantity = available_quantity - :qty, reserved_quantity = reserved_quantity + :qty
WHERE product_id = :pid AND warehouse_id = :wid AND available_quantity >= :qty
```

If two requests race for the last unit, Postgres serializes the two
`UPDATE`s on that row; the loser's `WHERE` clause is re-evaluated against
the winner's committed result and matches 0 rows, so it correctly reports
`INSUFFICIENT_INVENTORY`. No `SERIALIZABLE` isolation or manual locking
needed — this is standard `READ COMMITTED` behavior. See
**[docs/decisions/0001-concurrency-strategy.md](docs/decisions/0001-concurrency-strategy.md)**
for the full write-up (including why this was chosen over
`SELECT FOR UPDATE`), and
`tests/concurrency/test_concurrent_reservation.py` for the automated proof.

Transaction boundary: `order_service.create_order` reserves inventory for
every line item, creates the order + reservations + outbox event, **in one
transaction**. If any line item can't be reserved, the whole transaction
rolls back — an order is never left half-reserved.

## How idempotency is implemented

A dedicated `idempotency_keys` table plus a claim/lock protocol: the first
request to use a key `INSERT`s a row (relying on the primary-key
constraint to make exactly one request "win" a race), does its work, and
records the response; a concurrent or later request with the same key
`SELECT ... FOR UPDATE`s the existing row (blocking until it's settled) and
replays the stored response instead of creating a second order. Reusing a
key with a materially different request body is rejected with
`400 INVALID_REQUEST` rather than silently returning a mismatched cached
response. Full detail, including how a failed attempt avoids permanently
"poisoning" a key:
**[docs/decisions/0002-idempotency.md](docs/decisions/0002-idempotency.md)**.

## Order lifecycle

```
PENDING -> RESERVED -> PROCESSING -> COMPLETED   (payment_token: "success")
PENDING -> RESERVED -> PROCESSING -> FAILED       (payment_token: "fail")
PENDING -> RESERVED -(retry x2, backoff 5s/30s)-> FAILED   (payment_token: "fail_retryable")
RESERVED -> CANCELLED           (client cancels; PENDING is also cancellable)
RESERVED -> EXPIRED             (reservation timeout elapses, default 15 min)
```

`payment_token` is an optional field on `POST /api/v1/orders` (default
`"success"`) that deterministically selects the simulated payment outcome
— not part of the PRD's literal example schema, added because
section 10 requires deterministic success/fail behavior and there was
otherwise no way for a caller to choose which branch to exercise.
`COMPLETED` permanently consumes the reservation (`reserved_quantity`
decreases; `available_quantity` was already decremented at reservation
time); `FAILED`/`CANCELLED`/`EXPIRED` release it
(`available_quantity` restored, `reserved_quantity` decreases).

## Low-stock alerts

A small add-on, layered on top of the core reservation flow without
touching it (PRD: "Add a low-stock alert feature without changing the
existing order flow"):

```
PUT  /api/v1/inventory/{product_id}/warehouses/{warehouse_id}/low-stock-threshold   {"threshold": 5}
GET  /api/v1/inventory/low-stock[?warehouse_id=wh_001]
```

An admin sets a non-negative threshold per `(product, warehouse)` pair; the
system reacts to inventory *crossing* down through that threshold (not to
the current quantity — repeatedly checking "is stock below X" would
re-alert on every read while stock stays low), creates exactly one alert
per crossing, and resets once restocked above the threshold so the next
crossing alerts again. Every mutation of `available_quantity` (reserve,
release, manual adjustment) atomically checks for a crossing in the same
database transaction, using the identical compare-and-swap technique as
inventory reservation itself, so concurrent stock changes can't produce
duplicate alerts. Full rationale, including the two interview-question
alternatives considered and rejected:
**[docs/decisions/0005-low-stock-alerts.md](docs/decisions/0005-low-stock-alerts.md)**.

As a bonus extension, each alert also writes a transactional outbox event
(`LOW_STOCK_ALERT_CREATED`), relayed the same way as `ORDER_RESERVED`, to a
worker that simulates notifying the warehouse team by logging the event.

## Authentication & authorization

JWT bearer tokens (`Authorization: Bearer <token>`), issued by
`POST /api/v1/auth/login`. Two roles:

| Action | ADMIN | CLIENT |
|---|:---:|:---:|
| Create products / warehouses | ✅ | ❌ |
| Adjust / retrieve inventory | ✅ | ❌ |
| Configure low-stock threshold / list alerts | ✅ | ❌ |
| Create / retrieve / cancel **own** orders | — | ✅ |
| View **any** order | ✅ | own only |
| Look up a product by ID | ✅ | ✅ (needed to build an order) |

A `CLIENT` reading or cancelling another client's order gets
`403 FORBIDDEN`, not a leaked `404`-vs-`403` distinction either way — both
paths are guarded in `order_service.py`.

## Configuration

All configuration is environment-driven (`pydantic-settings`, reading a
`.env` file — see **[.env.example](.env.example)** for the full list with
inline explanations). No secret ever has a hardcoded fallback used in
Docker Compose; `.env` is git-ignored.

Highlights: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`,
`RESERVATION_TIMEOUT_MINUTES` (default 15, per PRD section 5.5),
`RESERVATION_CLEANUP_INTERVAL_SECONDS` (Celery Beat cadence),
`PAYMENT_RETRY_BACKOFF_SECONDS` / `PAYMENT_MAX_ATTEMPTS` (Bonus A),
`DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` (bootstrap admin).

## Important architectural decisions

Each of the PRD's required engineering-decision topics is written up in
full under `docs/decisions/`:

- **[0001 — Inventory concurrency strategy](docs/decisions/0001-concurrency-strategy.md)**
- **[0002 — Idempotency-Key implementation](docs/decisions/0002-idempotency.md)**
- **[0003 — Transactional outbox pattern](docs/decisions/0003-outbox-pattern.md)** (answers "what if the API commits but crashes before publishing?")
- **[0004 — IDs, warehouse selection, worker retries](docs/decisions/0004-ids-warehouse-selection-retries.md)**
- **[0005 — Low-stock alerts](docs/decisions/0005-low-stock-alerts.md)** (feature add-on: crossing detection, concurrency, notification idempotency, per-warehouse thresholds)

A few more, briefly:

- **Duplicate message processing** (interview Q29): `process_order` locks
  the order row and only acts if `status == RESERVED`; a duplicate
  delivery of the same message always finds a non-`RESERVED` status and
  no-ops. See `src/workers/order_processor.py`.
- **Double-release safety** (interview Q30): every release/consume
  operation is a conditional `UPDATE ... WHERE status = 'ACTIVE'`
  (`src/repositories/reservation_repository.py`), so running the
  expiration scheduler twice, or racing it against a cancellation, can
  never apply the same inventory change twice.
- **Domain logic vs. controllers**: `api/` routers do request
  parsing/auth/status-codes only and call straight into `services/`;
  `services/` own transaction boundaries (`db.commit()`/`db.rollback()`)
  and raise typed `AppError` subclasses; `repositories/` are one function
  per query, no business rules, no exceptions beyond what the DB itself
  raises.

## Bonus features implemented

| Bonus | Status | Notes |
|---|---|---|
| A — Retry with backoff | ✅ | `payment_token="fail_retryable"`: attempt 1 waits 5s, attempt 2 waits 30s, attempt 3 fails permanently — exact PRD example. Attempt count persisted in the DB, not just Celery's in-memory counter. |
| B — Dead-letter queue | ✅ (as a table) | `dead_letter_orders` records `(order_id, reason, attempts)` once `PAYMENT_MAX_ATTEMPTS` is exhausted — queryable for operator investigation without standing up a second physical queue. |
| C — Transactional outbox | ✅ | See decision doc 0003. This is the bonus with the highest correctness payoff for this project and was prioritized accordingly. |
| D — Prometheus metrics | ❌ | Not implemented — see "What I'd improve". |
| E — Rate limiting | ❌ | Not implemented — see "What I'd improve". |
| Low-stock alert notifications via outbox | ✅ | `LOW_STOCK_ALERT_CREATED` events reuse the same outbox/relay path as `ORDER_RESERVED`; see [Low-stock alerts](#low-stock-alerts). |

Per the PRD's own guidance ("a strong implementation of the core
requirements is more valuable than every bonus feature"), effort was
prioritized on correctness/concurrency/reliability of the core flow first;
D and E were the two lowest-leverage bonuses for that goal.

## Known limitations

- **Idempotency keys are never purged.** `idempotency_keys` grows
  unboundedly. A production system would add a Beat task deleting rows
  past a retention window (see decision doc 0002).
- **Inventory audit logs are append-only by convention, not by a DB
  trigger.** Nothing in Postgres physically prevents an `UPDATE`/`DELETE`
  against `inventory_audit_logs`; the guarantee is "the codebase never
  does this," enforced by code review, not the database.
- **A brand-new (product, warehouse) row created via
  `POST /inventory/adjustments` has a narrow race**: two concurrent
  first-time adjustments for the exact same pair can both pass the
  "does a row exist?" check and one will fail on the unique constraint at
  commit with a raw `500`, rather than a friendly `409`. This is an
  admin-only, low-frequency operation, so it wasn't worth the extra
  complexity of a `SELECT FOR UPDATE`/upsert here — unlike the
  customer-facing reservation path, which absolutely gets that treatment.
- **The outbox relay is poll-based** (default: every 1s), not push-based,
  so there's up to ~1s of added latency before an order starts processing.
  Acceptable for this scope; see "What I'd improve".
- **No rate limiting or metrics endpoint** (Bonus D/E) — see above.
- **Single-warehouse fulfillment per line item** — an order line is never
  split across warehouses (see decision doc 0004). A very large order for
  a product spread thin across many warehouses could be rejected as
  "insufficient inventory" even if the *sum* across warehouses would
  suffice.

## What I'd improve with more time

1. **Prometheus metrics** (Bonus D) — `orders_created_total`,
   `orders_completed_total`, `orders_failed_total`,
   `inventory_reservations_total`, `order_processing_duration` histogram,
   exposed at `/metrics` via `prometheus-client`.
2. **Rate limiting** (Bonus E) — per-client token bucket (keyed off the
   JWT subject) at the ASGI middleware layer, backed by Redis so it works
   correctly across multiple API replicas.
3. **CDC-based outbox relay** — replace the polling loop with a
   WAL-tailing relay (e.g. Debezium + Kafka Connect, or `pg_logical`) for
   near-zero-latency publication instead of a fixed poll interval, at the
   cost of real deployment complexity this project's scope didn't call for.
4. **Idempotency-key and outbox-event retention jobs**, per "Known
   limitations" above.
5. **Split line items across warehouses** when no single warehouse can
   satisfy a line alone, with a proper shipping-cost/complexity trade-off
   study once shipping is actually in scope.
6. **At 10,000 orders/sec** (interview Q32), the `inventory` table would
   be the first bottleneck — every reservation is a write to a small,
   hot set of rows. I'd shard hot products' inventory rows per-warehouse
   further (already partly true) and/or introduce a per-product in-memory
   reservation counter (Redis `DECR` with a Lua script for atomicity) as a
   fast-path admission check in front of Postgres, falling back to the
   database as the durable source of truth.
7. **Splitting into microservices** (interview Q33): Inventory/Reservation
   would be the first service extracted (it's the highest-contention,
   most latency-sensitive component and has the clearest bounded context),
   followed by Order Processing/Payment simulation; Product/Warehouse
   catalog data is low-write and could stay in the monolith or become a
   thin read-mostly service much later.

## License

[MIT](LICENSE) — free to use, copy, and modify, provided the copyright
notice is kept. Provided "as is", with no warranty; the author is not
liable for any outcome from using this software, including in production.
