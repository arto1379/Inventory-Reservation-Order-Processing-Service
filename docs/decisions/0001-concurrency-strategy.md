# 0001 — Inventory concurrency strategy

## Context

PRD section 7 requires that concurrent requests to reserve the last unit(s)
of a product never oversell: if two customers race for the last item,
exactly one must win.

## Options considered

1. **`SELECT ... FOR UPDATE` then `UPDATE`** — lock the row first, check
   availability in application code, then update. Correct, but holds the
   row lock for the entire surrounding transaction (product validation,
   order insert, reservation insert, audit insert, ...), which serializes
   unrelated work and increases lock-wait time under load.
2. **`SERIALIZABLE` isolation** — let Postgres detect the conflict and
   force one transaction to retry. Correct, but requires the *application*
   to catch serialization failures and retry the whole transaction, adding
   complexity throughout the order-creation path for a guarantee we can get
   more cheaply.
3. **Atomic conditional `UPDATE` ("compare-and-swap")** — chosen.

## Decision

```sql
UPDATE inventory
SET available_quantity = available_quantity - :qty,
    reserved_quantity  = reserved_quantity + :qty
WHERE product_id = :pid AND warehouse_id = :wid
  AND available_quantity >= :qty
```

Implemented in `src/repositories/inventory_repository.py::try_reserve`.

A single `UPDATE` statement is atomic. When two transactions race for the
same row, Postgres serializes them internally: the second transaction's
`UPDATE` blocks until the first commits or rolls back, then re-evaluates
its own `WHERE available_quantity >= :qty` against the **post-commit**
value, not the value it originally read. So if transaction A takes the
last unit, transaction B's `WHERE` clause fails to match — 0 rows
affected — and the caller correctly reports `INSUFFICIENT_INVENTORY`, with
zero risk of a lost-update race. This holds under Postgres's default
`READ COMMITTED` isolation; no `SERIALIZABLE` transactions, no advisory
locks, no explicit row locking are needed.

The same pattern is reused for releasing reservations
(`inventory_repository.release`), consuming them
(`inventory_repository.consume`), and manual adjustments
(`inventory_repository.adjust_available`) — every inventory mutation in
the codebase is a single guarded `UPDATE`.

Two `CHECK` constraints (`available_quantity >= 0`,
`reserved_quantity >= 0`) on the `inventory` table are the final backstop:
even a bug that bypassed the guarded `UPDATE` entirely could not drive
stock negative — Postgres would reject the write outright.

## Consequences

- Lock hold time per inventory row is minimized to a single statement,
  which is friendlier to throughput than holding a lock for a whole
  multi-step transaction.
- The trade-off is a possible "phantom read" between an earlier `SELECT`
  used to *choose* a warehouse (`find_best_warehouse`) and the `UPDATE`
  that actually reserves it. This is handled, not ignored: if that
  `UPDATE` affects 0 rows because another transaction won the race in
  between, `order_service.create_order` treats it exactly like
  insufficient inventory and rolls back the whole order — see
  `tests/concurrency/test_concurrent_reservation.py` for the automated
  proof this cannot oversell even at 100 simultaneous requests against 10
  units of stock.
