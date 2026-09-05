"""
Health endpoints (PRD section 23). Not versioned under /api/v1 since these
are typically probed by infrastructure (load balancers, orchestrators)
rather than API clients.
"""
import redis
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from src.config import settings
from src.database import engine

router = APIRouter(tags=["health"])


def _check_database() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _check_queue() -> bool:
    try:
        client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
        return bool(client.ping())
    except Exception:
        return False


@router.get("/health")
def health(response: Response) -> dict:
    """Aggregate liveness+readiness check: reports each dependency's status."""
    db_ok = _check_database()
    queue_ok = _check_queue()
    healthy = db_ok and queue_ok
    response.status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "healthy" if healthy else "unhealthy",
        "database": "connected" if db_ok else "unavailable",
        "queue": "connected" if queue_ok else "unavailable",
    }


@router.get("/health/live")
def health_live() -> dict:
    """Liveness probe: the process is up and able to respond at all. Does
    NOT check external dependencies -- a slow/down DB should not cause an
    orchestrator to kill and restart a perfectly healthy API process."""
    return {"status": "alive"}


@router.get("/health/ready")
def health_ready(response: Response) -> dict:
    """Readiness probe: the process can actually serve traffic (DB + queue
    reachable). Used by orchestrators to gate traffic routing."""
    db_ok = _check_database()
    queue_ok = _check_queue()
    ready = db_ok and queue_ok
    response.status_code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "not_ready", "database": db_ok, "queue": queue_ok}
