"""
Celery application instance shared by the worker, beat scheduler, and the
outbox relay (which enqueues tasks onto this same app).

Run with:
    celery -A src.workers.celery_app worker --loglevel=info
    celery -A src.workers.celery_app beat --loglevel=info
"""
from celery import Celery
from celery.schedules import schedule

from src.config import settings
from src.logging_config import configure_logging

configure_logging()

celery_app = Celery(
    "inventory_order_service",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["src.workers.order_processor", "src.workers.reservation_cleanup"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Workers acknowledge a task only after it finishes, so a worker that
    # crashes mid-task leaves the message unacked and Redis redelivers it --
    # part of why order processing must be idempotent (see order_processor.py).
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Celery Beat schedule: periodically sweep for expired reservations
# (PRD section 12). Interval is configurable via env var so tests/local dev
# can run it much faster than the 60s production default.
celery_app.conf.beat_schedule = {
    "expire-reservations": {
        "task": "workers.expire_reservations",
        "schedule": schedule(run_every=settings.reservation_cleanup_interval_seconds),
    }
}
