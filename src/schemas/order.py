"""Request/response schemas for orders (PRD FR-5, sections 13, 14)."""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.models.enums import OrderStatus
from src.schemas.common import PaginationMeta


class OrderItemRequest(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class OrderCreateRequest(BaseModel):
    items: list[OrderItemRequest] = Field(min_length=1)
    # See src/models/order.py docstring: lets tests/demos deterministically
    # choose the simulated payment outcome. Defaults to "success".
    payment_token: str = "success"

    @field_validator("items")
    @classmethod
    def no_duplicate_products(cls, items: list[OrderItemRequest]) -> list[OrderItemRequest]:
        product_ids = [i.product_id for i in items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("duplicate product_id in items; combine quantities into a single line instead")
        return items


class OrderItemResponse(BaseModel):
    product_id: str
    quantity: int
    unit_price: float

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: str
    status: OrderStatus
    total: float
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]
    pagination: PaginationMeta
