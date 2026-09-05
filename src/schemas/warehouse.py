"""Request/response schemas for warehouses (PRD FR-2)."""
from datetime import datetime

from pydantic import BaseModel, Field


class WarehouseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    location: str = Field(min_length=1, max_length=255)


class WarehouseResponse(BaseModel):
    id: str
    name: str
    location: str
    created_at: datetime

    model_config = {"from_attributes": True}
