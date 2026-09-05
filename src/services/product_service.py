"""Business logic for product management (PRD FR-1)."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.exceptions import DuplicateSkuError, ProductNotFoundError
from src.core.ids import generate_id
from src.models.product import Product
from src.repositories import product_repository
from src.schemas.product import ProductCreateRequest


def create_product(db: Session, payload: ProductCreateRequest) -> Product:
    """
    Create a product, rejecting duplicate SKUs with a clear domain error
    (PRD: "Duplicate SKUs must return an appropriate error").

    The pre-check below is purely a fast path for a friendly error message;
    the actual guarantee against two concurrent requests both creating the
    same SKU comes from the unique constraint on `products.sku`, so a race
    that slips past the pre-check still fails safely at commit time.
    """
    if product_repository.get_by_sku(db, payload.sku) is not None:
        raise DuplicateSkuError(f"A product with sku '{payload.sku}' already exists", {"sku": payload.sku})

    product = Product(id=generate_id("prod"), sku=payload.sku, name=payload.name, price=payload.price)
    product_repository.create(db, product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateSkuError(f"A product with sku '{payload.sku}' already exists", {"sku": payload.sku}) from exc
    db.refresh(product)
    return product


def get_product_or_404(db: Session, product_id: str) -> Product:
    product = product_repository.get_by_id(db, product_id)
    if product is None:
        raise ProductNotFoundError(f"Product '{product_id}' was not found", {"product_id": product_id})
    return product
