"""
Shared pytest fixtures.

Tests run against a REAL PostgreSQL database (TEST_DATABASE_URL from
.env.example -- docker-compose's `postgres` service auto-creates
`inventory_db_test` for this purpose, see scripts/init-test-db.sql). This is
a deliberate choice: the whole point of this project is DB-level
concurrency behaviour (row locking, conditional UPDATEs, unique
constraints), none of which SQLite can faithfully reproduce. See README >
"How to run tests".

IMPORTANT: the `DATABASE_URL` environment variable is overridden with
`TEST_DATABASE_URL` *before* anything under `src/` is imported, below. Every
module in this codebase (the API, the Celery worker, the reservation
scheduler, the outbox relay) reaches the database through
`src.database.SessionLocal`, which is bound once at import time to whatever
`DATABASE_URL` resolves to. Overriding it here -- rather than maintaining a
second, parallel test-only engine -- means a test can call `process_order()`
or `expire_reservations()` directly and know it is operating on the exact
same database the `client` fixture's HTTP requests just wrote to.

Schema is created directly from the SQLAlchemy models (`Base.metadata.
create_all`) rather than by running Alembic migrations, so the test suite
doesn't depend on migration history -- it always tests against "what the
current models say the schema should be". Migrations themselves are
exercised separately (`alembic upgrade head`) when the API container starts.
"""
import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/inventory_db_test",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import src.models  # noqa: E402,F401 -- populates Base.metadata
from src.api.deps import get_db  # noqa: E402
from src.core.ids import generate_id  # noqa: E402
from src.core.security import create_access_token, hash_password  # noqa: E402
from src.database import Base, SessionLocal, engine  # noqa: E402
from src.main import app  # noqa: E402
from src.models.enums import UserRole  # noqa: E402
from src.models.inventory import Inventory  # noqa: E402
from src.models.product import Product  # noqa: E402
from src.models.user import User  # noqa: E402
from src.models.warehouse import Warehouse  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _celery_eager_mode():
    """
    Run Celery tasks synchronously, in-process, with no broker at all.

    Tests never need a running Redis/worker: `task.delay(...)` executes the
    task body immediately and returns its real result, which is exactly
    what `tests/integration/test_outbox_relay.py` relies on to assert the
    order worker actually ran as a result of relaying an outbox event.
    """
    from src.workers.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate every table after each test so tests never leak state into
    one another, regardless of what they committed."""
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    """A TestClient wired to use `db_session` for every request, so a test
    can freely mix direct repository/service calls with real HTTP calls
    against the same in-flight data."""

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _make_user(db_session, role: UserRole) -> User:
    user = User(
        id=generate_id("user"),
        email=f"{role.value.lower()}-{generate_id('t')}@example.com",
        hashed_password=hash_password("irrelevant"),
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin_user(db_session) -> User:
    return _make_user(db_session, UserRole.ADMIN)


@pytest.fixture
def client_user(db_session) -> User:
    return _make_user(db_session, UserRole.CLIENT)


def _auth_headers(user: User) -> dict:
    token = create_access_token(subject=user.id, email=user.email, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(admin_user) -> dict:
    return _auth_headers(admin_user)


@pytest.fixture
def client_headers(client_user) -> dict:
    return _auth_headers(client_user)


@pytest.fixture
def product(db_session) -> Product:
    p = Product(id=generate_id("prod"), sku=f"SKU-{generate_id('x')}", name="Test Product", price=100.00)
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


@pytest.fixture
def warehouse(db_session) -> Warehouse:
    w = Warehouse(id=generate_id("wh"), name="Test Warehouse", location="Testville")
    db_session.add(w)
    db_session.commit()
    db_session.refresh(w)
    return w


def make_inventory(
    db_session,
    product: Product,
    warehouse: Warehouse,
    available: int,
    reserved: int = 0,
    low_stock_threshold: int | None = None,
) -> Inventory:
    inv = Inventory(
        id=generate_id("inv"),
        product_id=product.id,
        warehouse_id=warehouse.id,
        available_quantity=available,
        reserved_quantity=reserved,
        low_stock_threshold=low_stock_threshold,
        is_low_stock=low_stock_threshold is not None and available <= low_stock_threshold,
    )
    db_session.add(inv)
    db_session.commit()
    db_session.refresh(inv)
    return inv


@pytest.fixture
def inventory_factory(db_session):
    """Returns a callable so a test can create inventory with whatever
    quantities it needs: `inventory_factory(product, warehouse, available=10)`,
    optionally pre-configured with a low-stock threshold."""

    def _factory(
        product: Product,
        warehouse: Warehouse,
        available: int,
        reserved: int = 0,
        low_stock_threshold: int | None = None,
    ) -> Inventory:
        return make_inventory(db_session, product, warehouse, available, reserved, low_stock_threshold)

    return _factory
