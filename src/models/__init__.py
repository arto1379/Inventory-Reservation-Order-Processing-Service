"""
Import every model module here so that `Base.metadata` is fully populated
as soon as `src.models` is imported anywhere (Alembic's `env.py` and the
test suite's `Base.metadata.create_all()` both rely on this).
"""
from src.models.audit_log import InventoryAuditLog  # noqa: F401
from src.models.dead_letter import DeadLetterOrder  # noqa: F401
from src.models.idempotency import IdempotencyKey  # noqa: F401
from src.models.inventory import Inventory  # noqa: F401
from src.models.low_stock_alert import LowStockAlert  # noqa: F401
from src.models.order import Order, OrderItem  # noqa: F401
from src.models.outbox import OutboxEvent  # noqa: F401
from src.models.product import Product  # noqa: F401
from src.models.reservation import InventoryReservation  # noqa: F401
from src.models.user import User  # noqa: F401
from src.models.warehouse import Warehouse  # noqa: F401
