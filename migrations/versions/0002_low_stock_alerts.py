"""low-stock alerts feature add-on

Adds `low_stock_threshold` / `is_low_stock` to `inventory` (state needed to
detect a threshold crossing) and the `low_stock_alerts` table (one
immutable row per crossing). See docs/decisions/0005-low-stock-alerts.md.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-05
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("inventory", sa.Column("low_stock_threshold", sa.Integer, nullable=True))
    op.add_column(
        "inventory", sa.Column("is_low_stock", sa.Boolean, nullable=False, server_default=sa.false())
    )
    op.create_check_constraint(
        "ck_inventory_low_stock_threshold_nonnegative",
        "inventory",
        "low_stock_threshold IS NULL OR low_stock_threshold >= 0",
    )

    op.create_table(
        "low_stock_alerts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("product_id", sa.String(64), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("warehouse_id", sa.String(64), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("quantity_at_alert", sa.Integer, nullable=False),
        sa.Column("threshold", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_low_stock_alerts_product_id", "low_stock_alerts", ["product_id"])
    op.create_index("ix_low_stock_alerts_warehouse_id", "low_stock_alerts", ["warehouse_id"])
    op.create_index("ix_low_stock_alerts_created_at", "low_stock_alerts", ["created_at"])


def downgrade() -> None:
    op.drop_table("low_stock_alerts")
    op.drop_constraint("ck_inventory_low_stock_threshold_nonnegative", "inventory", type_="check")
    op.drop_column("inventory", "is_low_stock")
    op.drop_column("inventory", "low_stock_threshold")
