"""Data access for the `products` table."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.product import Product


def get_by_id(db: Session, product_id: str) -> Product | None:
    return db.get(Product, product_id)


def get_by_sku(db: Session, sku: str) -> Product | None:
    return db.execute(select(Product).where(Product.sku == sku)).scalar_one_or_none()


def get_many_by_ids(db: Session, product_ids: list[str]) -> dict[str, Product]:
    """Bulk-fetch products, returned as a dict keyed by id for O(1) lookups
    while validating an order's line items."""
    rows = db.execute(select(Product).where(Product.id.in_(product_ids))).scalars().all()
    return {p.id: p for p in rows}


def create(db: Session, product: Product) -> Product:
    db.add(product)
    db.flush()
    return product
