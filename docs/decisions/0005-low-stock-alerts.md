# 0005 — Low-Stock Alerts (feature add-on)

## Context

The Low-Stock Alerts PRD asks for an alert to fire exactly once when a
product/warehouse's available inventory crosses *down through* an
admin-configured threshold ("reacts to the crossing, not simply to the
current quantity"), never re-alerts while it stays low, resets once
restocked above the threshold, and must not double-alert under concurrent
inventory changes — all without touching the existing order flow.

## Where the state lives

`low_stock_threshold` and `is_low_stock` were added directly to the
`inventory` row (PRD section 5's "optional inventory fields" option),
rather than a separate `low_stock_config` table. Every write path that
needs to inspect or flip this state (`reserve`, `release`,
`adjust_available`) is already holding/mutating that exact row, so
co-locating the state avoids an extra join or a second table to keep in
sync, and — critically for concurrency (below) — lets the crossing check
reuse the same row lock the quantity change already took. `low_stock_alerts`
stays a separate, append-only table: it's a *history* of crossings, not
current state, the same relationship `inventory_audit_logs` has to
`inventory` itself.

## Detecting the crossing, not the level (interview Q1)

Checking "is available_quantity <= threshold right now" on every read would
alert repeatedly for as long as stock stays low (violates FR-3) and
provides no way to tell "still low" apart from "just became low" (which is
the only one that should notify anyone). Instead, `is_low_stock` is a
tri-state-free boolean recording *whether an alert is currently open* for
this pair, and the transition itself — not the level — is what creates a
row in `low_stock_alerts`:

```python
# src/repositories/inventory_repository.py
def try_flip_low_stock(db, product_id, warehouse_id):
    stmt = (
        update(Inventory)
        .where(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
            Inventory.is_low_stock.is_(False),          # FR-3: only an *entering* crossing
            Inventory.low_stock_threshold.isnot(None),
            Inventory.available_quantity <= Inventory.low_stock_threshold,
        )
        .values(is_low_stock=True)
        .returning(Inventory.available_quantity, Inventory.low_stock_threshold)
    )
    return db.execute(stmt).first()   # None => no alert; a Row => exactly one alert
```

`try_reset_low_stock` is the mirror image (`is_low_stock.is_(True)` and
`available_quantity > threshold` → flip back to False), which is what lets
the next decrease alert again (FR-4, FR-5).

## Preventing duplicate alerts under concurrency (interview Q2)

Section 6 requires that racing inventory decreases can't double-alert for
the same crossing. `try_flip_low_stock` is the exact compare-and-swap
pattern already used for reservations
(`docs/decisions/0001-concurrency-strategy.md`): the `WHERE is_low_stock =
false` clause means only one of any number of concurrent transactions
racing to update this row can ever see its `UPDATE` actually match and
return a row. Postgres serializes concurrent `UPDATE`s to the same row and
re-evaluates each waiting transaction's `WHERE` against the *post-commit*
value, so the second transaction to reach this statement always finds
`is_low_stock` already `true` and matches zero rows — no alert, correctly.

This holds even though quantity-decrement and crossing-detection are two
separate `UPDATE` statements (`try_reserve` then `try_flip_low_stock`),
because Postgres holds a row-level lock for the entire enclosing
transaction, not per-statement: once a transaction's first `UPDATE` touches
the row, no other transaction's `UPDATE` against that row can proceed until
the first commits or rolls back. So the second statement in the same
transaction never contends with anyone — it's simply reading back its own
uncommitted write. `tests/concurrency/test_concurrent_low_stock_alerts.py`
proves this directly: 100 simultaneous 1-unit reservations against 10 units
of stock with a threshold of 5 produce exactly one alert.

An alternative considered: a unique constraint on
`(product_id, warehouse_id, "open")` in `low_stock_alerts` with an
`INSERT ... ON CONFLICT DO NOTHING`. Rejected because it needs a second
table read/write to answer "am I already low-stock?" (there's no `open`
flag to key a partial unique index on without adding exactly the boolean
this decision already puts on `inventory`), whereas the chosen approach
reuses a column and a lock the caller already has.

## Where the alert state is stored (interview Q3)

Covered above: on `inventory` because every mutator already owns that row's
lock; `low_stock_alerts` is the audit trail FR-6 reads from, structurally
identical in spirit to `inventory_audit_logs`.

## Notification worker idempotency (interview Q4)

The alert row and its outbox event are written in the same transaction as
the inventory change that caused them (`inventory_service.
_check_low_stock_transition`), reusing the transactional-outbox guarantee
from `docs/decisions/0003-outbox-pattern.md` verbatim: a crash can't lose
the notification, at the cost of possible duplicate delivery. Unlike order
processing, `notify_low_stock_task` (`src/workers/low_stock_notifier.py`)
has no state a duplicate delivery could corrupt — it only logs — so no
additional idempotency guard was added. If a real notification channel
(email/Slack) replaced the log line, the natural guard would be keying
delivery on `alert_id`, which the outbox payload already carries.

## Per-warehouse thresholds (interview Q5)

Already the default shape: the threshold lives on the
`(product_id, warehouse_id)` row, so two warehouses for the same product
carry independent thresholds and independent `is_low_stock` state with no
extra modeling. `PUT /inventory/{product_id}/warehouses/{warehouse_id}/low-stock-threshold`
and `GET /inventory/low-stock?warehouse_id=...` both operate at that same
granularity.

## Threshold (re)configuration doesn't itself alert

`inventory_repository.set_threshold` recomputes `is_low_stock` against the
row's current quantity in the same `UPDATE` that changes the threshold, but
this is a plain assignment, not a call to `try_flip_low_stock` — no
`low_stock_alerts` row is written. FR-2 says an alert fires when inventory
*moves* across the threshold; reconfiguring the threshold around an
unchanged quantity is not a movement, so it silently updates the state a
future movement will correctly react to instead of firing a synthetic
alert for a crossing that never happened.

## Existing order flow is untouched

No table used by order creation/reservation/processing was altered.
`_check_low_stock_transition` is additive: called from `reserve`, `release`
and `adjust_available` after they've already decided the mutation
succeeds, and it never raises — `order_service.create_order` and the
reservation-expiry/cancellation paths are unaware this feature exists.
