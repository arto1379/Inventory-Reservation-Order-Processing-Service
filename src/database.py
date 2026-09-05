"""
SQLAlchemy engine/session setup.

The whole codebase uses *synchronous* SQLAlchemy sessions (not asyncio).
This is a deliberate choice, explained in detail in the README's
"Important architectural decisions" section:

  - The core hard part of this project is correct transaction/locking
    behaviour around inventory reservation. Synchronous sessions make
    transaction boundaries (`with SessionLocal() as db: ... db.commit()`)
    trivial to reason about and to unit test.
  - The Celery worker ecosystem is synchronous by nature; sharing one
    session-management style between the API and the worker avoids running
    two different database access stacks in the same codebase.
  - FastAPI runs sync `def` path functions in a thread pool automatically,
    so we don't lose the ability to serve concurrent requests.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from src.config import settings

# `pool_pre_ping` avoids handing out dead connections after the DB restarts
# or an idle connection is dropped by a firewall/load balancer. The pool is
# sized generously (default SQLAlchemy is only 5+10) since order creation
# briefly holds a connection per concurrent request while it reserves
# inventory -- see tests/concurrency/test_concurrent_reservation.py, which
# opens dozens of simultaneous connections against this same engine.
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=20, max_overflow=20, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Shared declarative base class for every ORM model in the project."""


# The FastAPI `get_db` dependency lives in `src/api/deps.py` (alongside the
# auth dependencies that build on top of it), not here -- this module only
# owns engine/session construction.
