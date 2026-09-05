# 0003 — Transactional outbox for async order processing (Bonus C)

## Context (interview question 28)

"What happens if your API commits an order to PostgreSQL but crashes
before publishing the queue message?"

Without an outbox, the natural implementation is:

```python
db.commit()
process_order_task.delay(order_id)   # <-- crash here loses the message forever
```

A crash, a Redis blip, or a deploy landing exactly between these two lines
leaves a `RESERVED` order that will never be processed — inventory stays
reserved, the customer's payment is never simulated, and nothing in the
system knows anything is wrong.

## Decision

Write an `outbox_events` row (`aggregate_type="order"`,
`event_type="ORDER_RESERVED"`, `payload={"order_id": ...}`) in the **same
transaction and commit** as the order/reservation inserts
(`order_service.create_order`, step 4). A separate long-running process,
`src/workers/outbox_relay.py`, polls this table for `PENDING` rows and:

```python
process_order_task.delay(payload["order_id"])
outbox_repository.mark_published(db, event.id)
db.commit()
```

only marking a row `PUBLISHED` *after* the Celery `.delay()` call returns.

## Consequences

- A crash between "commit the order" and "enqueue the task" is now
  impossible to lose: the outbox row is committed atomically with the
  order, so it is guaranteed to exist and be `PENDING` until successfully
  relayed.
- A crash between "enqueue the task" and "mark the row `PUBLISHED`"
  produces a **duplicate** delivery on the next poll — traded deliberately
  for the stronger guarantee above. This is why `process_order` (interview
  question 29) must be, and is, idempotent against being invoked twice for
  the same order: it locks the order row and only acts if
  `status == RESERVED`, so a duplicate delivery after the order already
  moved to `PROCESSING`/`COMPLETED`/`FAILED` safely no-ops. See
  `src/workers/order_processor.py`'s module docstring.
- Claiming a batch of outbox rows uses
  `SELECT ... FOR UPDATE SKIP LOCKED`, so running more than one relay
  replica for throughput/HA is safe out of the box — they partition the
  work instead of double-processing it.
- The relay is a simple polling loop (default: every
  `OUTBOX_POLL_INTERVAL_SECONDS = 1`), not push-based. At this project's
  scale that's an acceptable latency trade-off for a dramatically simpler
  implementation than a CDC-based outbox (e.g. Debezium tailing the WAL).
  See README "What I'd improve with more time".
