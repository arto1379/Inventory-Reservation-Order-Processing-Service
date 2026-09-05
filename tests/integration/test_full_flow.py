"""
End-to-end happy-path integration test matching PRD section 24's required
flow: Create product -> Add inventory -> Create order -> Reserve inventory
-> Process payment -> Complete order. Also checks the audit trail (section 15).
"""
from src.models.enums import AuditEventType
from src.repositories import audit_repository
from src.workers.order_processor import process_order


def test_full_order_lifecycle(client, admin_headers, client_headers, db_session):
    # 1. Create product
    product = client.post(
        "/api/v1/products", json={"sku": "GPU-RTX5090", "name": "RTX 5090", "price": 2499.99}, headers=admin_headers
    ).json()

    # 2. Create warehouse
    warehouse = client.post(
        "/api/v1/warehouses", json={"name": "Vancouver Warehouse", "location": "Vancouver, BC"}, headers=admin_headers
    ).json()

    # 3. Add inventory
    adjustment = client.post(
        "/api/v1/inventory/adjustments",
        json={"product_id": product["id"], "warehouse_id": warehouse["id"], "quantity": 50, "reason": "warehouse_delivery"},
        headers=admin_headers,
    )
    assert adjustment.status_code == 201
    assert adjustment.json()["available_quantity"] == 50

    # 4. Create order (reserves inventory as part of the same call)
    order = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": product["id"], "quantity": 2}], "payment_token": "success"},
        headers=client_headers,
    ).json()
    assert order["status"] == "RESERVED"
    assert order["total"] == 4999.98

    inventory_after_reserve = client.get(f"/api/v1/inventory/{product['id']}", headers=admin_headers).json()
    assert inventory_after_reserve["warehouses"][0]["available"] == 48
    assert inventory_after_reserve["warehouses"][0]["reserved"] == 2

    # 5. Process payment / complete order (normally done by the async worker)
    process_order(order["id"])

    final_order = client.get(f"/api/v1/orders/{order['id']}", headers=client_headers).json()
    assert final_order["status"] == "COMPLETED"

    inventory_after_complete = client.get(f"/api/v1/inventory/{product['id']}", headers=admin_headers).json()
    assert inventory_after_complete["warehouses"][0]["available"] == 48
    assert inventory_after_complete["warehouses"][0]["reserved"] == 0

    # Audit trail: stock added, then reserved, then consumed on completion.
    audit_entries = audit_repository.list_for_product(db_session, product["id"])
    event_types = [entry.type for entry in reversed(audit_entries)]  # chronological order
    assert event_types == [
        AuditEventType.STOCK_ADDED,
        AuditEventType.INVENTORY_RESERVED,
        AuditEventType.ORDER_COMPLETED,
    ]
