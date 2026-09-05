"""
Shared enumerations used across models, schemas, and services.

Centralizing these avoids subtle bugs where the API layer, the DB layer, and
the worker layer each hardcode slightly different string literals for the
same concept (e.g. "COMPLETED" vs "completed").
"""
import enum


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    CLIENT = "CLIENT"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


# Order statuses from which cancellation is still allowed (PRD section 13).
CANCELLABLE_ORDER_STATUSES = {OrderStatus.PENDING, OrderStatus.RESERVED}

# Terminal states: once here, an order never transitions again.
TERMINAL_ORDER_STATUSES = {
    OrderStatus.COMPLETED,
    OrderStatus.FAILED,
    OrderStatus.CANCELLED,
    OrderStatus.EXPIRED,
}


class ReservationStatus(str, enum.Enum):
    # Actively holding inventory (counted in inventory.reserved_quantity).
    ACTIVE = "ACTIVE"
    # Released back to available stock (order failed/cancelled/expired).
    RELEASED = "RELEASED"
    # Permanently consumed by a completed order (reserved_quantity was
    # decremented; this reservation will never be released).
    CONSUMED = "CONSUMED"


class AuditEventType(str, enum.Enum):
    STOCK_ADDED = "STOCK_ADDED"
    STOCK_REMOVED = "STOCK_REMOVED"
    INVENTORY_RESERVED = "INVENTORY_RESERVED"
    RESERVATION_RELEASED = "RESERVATION_RELEASED"
    ORDER_COMPLETED = "ORDER_COMPLETED"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class IdempotencyStatus(str, enum.Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class OutboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"


class PaymentResult(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
