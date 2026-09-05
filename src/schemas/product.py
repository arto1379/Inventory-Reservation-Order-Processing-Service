"""Request/response schemas for products (PRD FR-1)."""
from datetime import datetime

from pydantic import BaseModel, Field


class ProductCreateRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    price: float = Field(gt=0)


class ProductResponse(BaseModel):
    id: str
    sku: str
    name: str
    price: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
