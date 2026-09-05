# Running the test suite on a VPS

Assumes the stack is already installed per `docs/vps-install.md`. The test
suite needs a real Postgres instance (see `CLAUDE.md` — the whole point of
these tests is exercising Postgres-level locking, which SQLite can't
reproduce) but does **not** need Redis or Celery: `tests/conftest.py` runs
Celery in eager mode, so `.delay()` executes synchronously in-process with
no broker.

**Run this only on a staging/test VPS, or a VPS not yet serving production
traffic.** Every test truncates the tables it touches in `TEST_DATABASE_URL`
after each test runs — it's a separate database from the app's, but it's
still real Postgres doing real writes, and the concurrency suite spins up
100 concurrent connections against it, which will compete for resources with
anything else live on the same box.

## 1. Bring up just Postgres

If the full stack from `vps-install.md` is already running, its `postgres`
service already has `inventory_db_test` created (via
`scripts/init-test-db.sql`, which runs once against the fresh volume) and is
what you want — skip to step 2.

Starting from nothing:

```bash
docker compose up -d postgres
```

## 2. Install Python deps for running pytest directly

The `api` image already has everything installed, so the simplest path is
running pytest *inside* that container rather than setting up a separate
venv on the host:

```bash
docker compose run --rm api pytest
```

This reuses the same image, mounts the same code (via the `volumes: - .:/app`
bind mount in `docker-compose.yml`), and reaches Postgres over the compose
network at `postgres:5432` — no extra config needed since `TEST_DATABASE_URL`
in `.env` already points there in the Docker Compose context... except by
default `.env.example` sets `TEST_DATABASE_URL` to `localhost:5432` (for the
common case of running pytest directly on a host that has `postgres` exposed
on `localhost`). Inside a container, `localhost` refers to the container
itself, not the `postgres` service. Override it for this run:

```bash
docker compose run --rm -e TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/inventory_db_test api pytest
```

Alternatively, run pytest directly on the VPS host against the
compose-exposed port (works as-is with the default `.env.example` value
since `postgres:5432` is published to the host):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest
```

## 3. Useful subsets

```bash
pytest --cov=src                                    # with coverage
pytest tests/concurrency -v                          # the 100-concurrent-request suite
pytest tests/unit/test_inventory_service.py          # one file
pytest -m "not concurrency"                          # skip the slow concurrency suite
```

(Swap `pytest ...` for `docker compose run --rm api pytest ...` if running
inside the container per step 2.)

## 4. CI-style one-shot run

For a scripted/CI invocation that tears everything down afterward:

```bash
docker compose up -d postgres
docker compose run --rm -e TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/inventory_db_test api pytest
docker compose down -v postgres   # -v also drops the postgres_data volume; omit if you want to keep it
```

## Troubleshooting

- `sqlalchemy.exc.OperationalError: could not connect to server`: Postgres
  isn't up yet or `TEST_DATABASE_URL`'s host is wrong (see the
  `localhost` vs `postgres` note in step 2).
- `database "inventory_db_test" does not exist`: `scripts/init-test-db.sql`
  only runs against a *fresh* Postgres data volume. If you reused an old
  volume that predates this script, create it manually:
  `docker compose exec postgres psql -U postgres -c "CREATE DATABASE inventory_db_test;"`
- Concurrency tests time out or run much slower than expected: a small VPS
  (1 vCPU) genuinely can't dispatch 100 concurrent DB connections quickly —
  this affects wall-clock time, not correctness. Don't run the concurrency
  suite concurrently with anything else hitting the same Postgres instance.
