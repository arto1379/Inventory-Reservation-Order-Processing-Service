"""Integration tests for FR-1 (products) and RBAC enforcement."""


def test_admin_can_create_product(client, admin_headers):
    resp = client.post(
        "/api/v1/products",
        json={"sku": "KB-MX-001", "name": "Mechanical Keyboard", "price": 149.99},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["sku"] == "KB-MX-001"
    assert body["id"].startswith("prod_")


def test_duplicate_sku_is_rejected(client, admin_headers):
    payload = {"sku": "GPU-RTX5090", "name": "RTX 5090", "price": 2499.99}
    first = client.post("/api/v1/products", json=payload, headers=admin_headers)
    assert first.status_code == 201

    second = client.post("/api/v1/products", json=payload, headers=admin_headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "DUPLICATE_SKU"


def test_client_role_cannot_create_product(client, client_headers):
    resp = client.post(
        "/api/v1/products", json={"sku": "X-1", "name": "X", "price": 1}, headers=client_headers
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_unauthenticated_request_is_rejected(client):
    resp = client.post("/api/v1/products", json={"sku": "X-2", "name": "X", "price": 1})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_get_unknown_product_returns_404(client, admin_headers):
    resp = client.get("/api/v1/products/prod_does_not_exist", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PRODUCT_NOT_FOUND"
