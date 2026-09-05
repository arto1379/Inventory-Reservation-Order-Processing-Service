"""Product endpoints (PRD FR-1). Create is ADMIN-only per section 16."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.api.deps import get_db, require_roles
from src.models.enums import UserRole
from src.schemas.product import ProductCreateRequest, ProductResponse
from src.services import product_service

router = APIRouter(prefix="/products", tags=["products"])


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def create_product(payload: ProductCreateRequest, db: Session = Depends(get_db)) -> ProductResponse:
    product = product_service.create_product(db, payload)
    return ProductResponse.model_validate(product)


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: str, db: Session = Depends(get_db), _current_user=Depends(require_roles(UserRole.ADMIN, UserRole.CLIENT))
) -> ProductResponse:
    """Both roles may look up a product (needed by CLIENT callers building
    an order)."""
    product = product_service.get_product_or_404(db, product_id)
    return ProductResponse.model_validate(product)
