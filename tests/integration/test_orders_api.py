"""
Integration tests for order creation, reservation, insufficient inventory,
idempotency, cancellation, and RBAC-scoped retrieval/listing (PRD FR-5,
sections 8, 13, 14).
"""


def test_create_order_reserves_inventory(client, client_headers, admin_headers, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=10)

    resp = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": product.id, "quantity": 3}]},
        headers=client_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "RESERVED"
    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 3

    inv_resp = client.get(f"/api/v1/inventory/{product.id}", headers=admin_headers)
    assert inv_resp.status_code == 200
    line = inv_resp.json()["warehouses"][0]
    assert line["available"] == 7
    assert line["reserved"] == 3


def test_insufficient_inventory_returns_409(client, client_headers, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=2)

    resp = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": product.id, "quantity": 5}]},
        headers=client_headers,
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "INSUFFICIENT_INVENTORY"
    assert body["error"]["details"] == {"requested": 5, "available": 2}


def test_unknown_product_in_order_returns_404(client, client_headers):
    resp = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": "prod_missing", "quantity": 1}]},
        headers=client_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


def test_idempotency_key_replays_same_order(client, client_headers, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=10)
    headers = {**client_headers, "Idempotency-Key": "test-key-123"}
    payload = {"items": [{"product_id": product.id, "quantity": 2}]}

    first = client.post("/api/v1/orders", json=payload, headers=headers)
    second = client.post("/api/v1/orders", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_idempotency_key_reused_with_different_payload_is_rejected(
    client, client_headers, product, warehouse, inventory_factory
):
    inventory_factory(product, warehouse, available=10)
    headers = {**client_headers, "Idempotency-Key": "test-key-456"}

    first = client.post(
        "/api/v1/orders", json={"items": [{"product_id": product.id, "quantity": 1}]}, headers=headers
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/orders", json={"items": [{"product_id": product.id, "quantity": 2}]}, headers=headers
    )
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "INVALID_REQUEST"


def test_client_cannot_view_another_clients_order(client, client_headers, product, warehouse, inventory_factory, db_session):
    from src.core.ids import generate_id
    from src.core.security import create_access_token, hash_password
    from src.models.enums import UserRole
    from src.models.user import User

    inventory_factory(product, warehouse, available=10)
    order = client.post(
        "/api/v1/orders", json={"items": [{"product_id": product.id, "quantity": 1}]}, headers=client_headers
    ).json()

    other = User(id=generate_id("user"), email="other@example.com", hashed_password=hash_password("x"), role=UserRole.CLIENT)
    db_session.add(other)
    db_session.commit()
    other_token = create_access_token(subject=other.id, email=other.email, role=other.role.value)

    resp = client.get(f"/api/v1/orders/{order['id']}", headers={"Authorization": f"Bearer {other_token}"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_cancel_reserved_order_releases_inventory(client, client_headers, admin_headers, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=10)
    order = client.post(
        "/api/v1/orders", json={"items": [{"product_id": product.id, "quantity": 4}]}, headers=client_headers
    ).json()

    cancel_resp = client.post(f"/api/v1/orders/{order['id']}/cancel", headers=client_headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"

    line = client.get(f"/api/v1/inventory/{product.id}", headers=admin_headers).json()["warehouses"][0]
    assert line["available"] == 10
    assert line["reserved"] == 0


def test_cancelling_already_cancelled_order_is_rejected(client, client_headers, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=10)
    order = client.post(
        "/api/v1/orders", json={"items": [{"product_id": product.id, "quantity": 1}]}, headers=client_headers
    ).json()
    client.post(f"/api/v1/orders/{order['id']}/cancel", headers=client_headers)

    second_cancel = client.post(f"/api/v1/orders/{order['id']}/cancel", headers=client_headers)
    assert second_cancel.status_code == 409
    assert second_cancel.json()["error"]["code"] == "ORDER_CANNOT_BE_CANCELLED"


def test_list_orders_supports_status_filter_and_pagination(client, client_headers, product, warehouse, inventory_factory):
    inventory_factory(product, warehouse, available=10)
    for _ in range(3):
        client.post(
            "/api/v1/orders", json={"items": [{"product_id": product.id, "quantity": 1}]}, headers=client_headers
        )

    resp = client.get("/api/v1/orders?status=RESERVED&page=1&limit=2", headers=client_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["pagination"]["total"] == 3
    assert body["pagination"]["total_pages"] == 2
    assert len(body["orders"]) == 2
    assert all(o["status"] == "RESERVED" for o in body["orders"])
