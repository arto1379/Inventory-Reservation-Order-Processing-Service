"""Data access for the immutable `inventory_audit_logs` table (PRD section 15)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.ids import generate_id
from src.models.audit_log import InventoryAuditLog
from src.models.enums import AuditEventType


def record(
    db: Session,
    *,
    product_id: str,
    warehouse_id: str,
    change: int,
    event_type: AuditEventType,
    reference_id: str,
) -> InventoryAuditLog:
    """Insert one immutable audit record. Never updated or deleted afterwards."""
    entry = InventoryAuditLog(
        id=generate_id("audit"),
        product_id=product_id,
        warehouse_id=warehouse_id,
        change=change,
        type=event_type,
        reference_id=reference_id,
    )
    db.add(entry)
    db.flush()
    return entry


def list_for_product(db: Session, product_id: str, limit: int = 100) -> list[InventoryAuditLog]:
    return list(
        db.execute(
            select(InventoryAuditLog)
            .where(InventoryAuditLog.product_id == product_id)
            .order_by(InventoryAuditLog.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
