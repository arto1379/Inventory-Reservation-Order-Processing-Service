"""Request/response schemas for the Low-Stock Alerts add-on (FR-1, FR-6)."""
from datetime import datetime

from pydantic import BaseModel, Field


class LowStockThresholdRequest(BaseModel):
    threshold: int = Field(ge=0, description="Non-negative low-stock threshold")


class LowStockThresholdResponse(BaseModel):
    product_id: str
    warehouse_id: str
    threshold: int
    is_low_stock: bool


class LowStockAlertResponse(BaseModel):
    id: str
    product_id: str
    warehouse_id: str
    quantity_at_alert: int
    threshold: int
    created_at: datetime

    model_config = {"from_attributes": True}


class LowStockAlertListResponse(BaseModel):
    alerts: list[LowStockAlertResponse]
