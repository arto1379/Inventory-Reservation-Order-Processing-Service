"""Request/response schemas for inventory endpoints (PRD FR-3, FR-4)."""
from pydantic import BaseModel, Field


class InventoryAdjustmentRequest(BaseModel):
    product_id: str
    warehouse_id: str
    # Positive to add stock, negative to remove stock (e.g. damaged goods).
    quantity: int = Field(description="Signed delta to apply to available_quantity")
    reason: str = Field(min_length=1, max_length=255)


class InventoryAdjustmentResponse(BaseModel):
    product_id: str
    warehouse_id: str
    available_quantity: int
    reserved_quantity: int


class WarehouseInventoryLine(BaseModel):
    warehouse_id: str
    available: int
    reserved: int


class ProductInventoryResponse(BaseModel):
    product_id: str
    warehouses: list[WarehouseInventoryLine]
