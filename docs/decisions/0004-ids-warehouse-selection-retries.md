# 0004 — IDs, warehouse selection, and worker retries

Three smaller decisions grouped together since each is a short,
self-contained rationale (PRD section 32 asks for all three explicitly).

## How IDs are generated

Every entity gets a prefixed UUID4, e.g. `generate_id("order")` ->
`order_9b1d4f...` (`src/core/ids.py`). UUID4 avoids the contention and
predictability problems of auto-increment primary keys under concurrent
inserts and lets an ID be generated in the service layer *before* the row
is inserted (used by the outbox pattern, where the order ID needs to exist
before the order/reservation/outbox rows are all built). The prefix
matches the PRD's own examples (`prod_123`, `order_123`) and makes IDs
self-describing in logs and URLs without a lookup.

## How warehouse selection works

A single line item is fulfilled from exactly one warehouse: the one with
the most available stock that can satisfy the full requested quantity on
its own (`inventory_repository.find_best_warehouse`, ordered by
`available_quantity DESC`). Orders are not split across warehouses for one
line item.

This is a deliberate simplification. Splitting an order line across
multiple warehouses would require the `order_items`/reservation model to
represent "3 units from warehouse A + 2 from warehouse B for the same
line", which cascades into shipping logistics that are explicitly out of
scope for this project. Preferring the warehouse with the *most* stock
(rather than, say, the nearest one) is a reasonable default in the absence
of a shipping/geolocation concern to optimize for; a real system would
plug a different warehouse-selection strategy in behind this same
function without touching `order_service.py`.

## How failed workers are retried

Retry state lives in the database (`orders.processing_attempts`), not only
in Celery's in-memory retry counter. `process_order` increments and checks
this counter itself, and only raises `RetryablePaymentError` (which the
Celery task wrapper turns into `self.retry(countdown=...)`) while attempts
remain under `PAYMENT_MAX_ATTEMPTS`. This means:

- The attempt count survives a worker process restart or redeploy.
- It's directly visible/auditable via a normal SQL query, not buried in
  Celery/Redis internal state.
- Celery's own `max_retries` is passed as a redundant safety net, but the
  database counter is the actual source of truth for "how many times has
  this order really been attempted".

Only the simulated-payment failure path retries. An unexpected exception
elsewhere in `process_order` (e.g. a DB connectivity blip) is **not**
auto-retried — it surfaces as a failed Celery task visible in monitoring,
which is preferable to silently masking a real bug behind a blind retry
loop. A production system would likely add a narrow `autoretry_for`
around genuinely transient infrastructure errors (connection resets)
without touching business-logic exceptions.
