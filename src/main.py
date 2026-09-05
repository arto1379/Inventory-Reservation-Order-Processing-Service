"""
FastAPI application entrypoint / composition root.

Wires together: structured logging, request-ID middleware, versioned API
routers, health endpoints, and the global exception handlers. Run with:

    uvicorn src.main:app --reload
"""
from fastapi import FastAPI

from src.api import auth, health, inventory, orders, products, warehouses
from src.config import settings
from src.logging_config import configure_logging
from src.middleware.error_handler import register_exception_handlers
from src.middleware.request_id import RequestIdMiddleware

configure_logging()

app = FastAPI(
    title="Inventory Reservation & Order Processing Service",
    description=(
        "Backend service for managing product inventory across warehouses, "
        "reserving stock safely under concurrent demand, and processing "
        "orders asynchronously with simulated payments."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(RequestIdMiddleware)
register_exception_handlers(app)

app.include_router(health.router)
app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(products.router, prefix=settings.api_v1_prefix)
app.include_router(warehouses.router, prefix=settings.api_v1_prefix)
app.include_router(inventory.router, prefix=settings.api_v1_prefix)
app.include_router(orders.router, prefix=settings.api_v1_prefix)
