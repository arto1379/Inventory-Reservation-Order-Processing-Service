"""Integration tests for the Low-Stock Alerts add-on's HTTP surface: FR-1
(configure threshold), FR-6 (list alerts), and RBAC (ADMIN-only, per the
existing convention for every /inventory endpoint)."""


def _threshold_url(product_id: str, warehouse_id: str) -> str:
    return f"/api/v1/inventory/{product_id}/warehouses/{warehouse_id}/low-stock-threshold"


def test_admin_can_set_threshold(client, admin_headers, product, warehouse):
    resp = client.put(_threshold_url(product.id, warehouse.id), json={"threshold": 5}, headers=admin_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["product_id"] == product.id
    assert body["warehouse_id"] == warehouse.id
    assert body["threshold"] == 5


def test_negative_threshold_is_rejected(client, admin_headers, product, warehouse):
    resp = client.put(_threshold_url(product.id, warehouse.id), json={"threshold": -1}, headers=admin_headers)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


def test_set_threshold_for_unknown_product_returns_404(client, admin_headers, warehouse):
    resp = client.put(_threshold_url("prod_does_not_exist", warehouse.id), json={"threshold": 5}, headers=admin_headers)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


def test_set_threshold_for_unknown_warehouse_returns_404(client, admin_headers, product):
    resp = client.put(_threshold_url(product.id, "wh_does_not_exist"), json={"threshold": 5}, headers=admin_headers)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "WAREHOUSE_NOT_FOUND"


def test_client_role_cannot_set_threshold(client, client_headers, product, warehouse):
    resp = client.put(_threshold_url(product.id, warehouse.id), json={"threshold": 5}, headers=client_headers)

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_list_low_stock_alerts_empty_by_default(client, admin_headers):
    resp = client.get("/api/v1/inventory/low-stock", headers=admin_headers)

    assert resp.status_code == 200
    assert resp.json() == {"alerts": []}


def test_list_low_stock_alerts_after_a_crossing(client, admin_headers, product, warehouse, inventory_factory, db_session):
    from src.services import inventory_service

    inventory_factory(product, warehouse, available=7, low_stock_threshold=5)

    # Drive the crossing through the service layer directly against the
    # same session the `client` fixture's HTTP requests use (see
    # conftest.py) -- the crossing itself is already covered end-to-end via
    # the order API in test_orders_api.py / test_full_flow.py; here we only
    # need one alert to exist to exercise the list endpoint.
    inventory_service.reserve(db_session, product_id=product.id, warehouse_id=warehouse.id, quantity=2, order_id="o1")
    db_session.commit()

    resp = client.get("/api/v1/inventory/low-stock", headers=admin_headers)
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["product_id"] == product.id
    assert alerts[0]["warehouse_id"] == warehouse.id
    assert alerts[0]["quantity_at_alert"] == 5
    assert alerts[0]["threshold"] == 5

    scoped = client.get(f"/api/v1/inventory/low-stock?warehouse_id={warehouse.id}", headers=admin_headers)
    assert len(scoped.json()["alerts"]) == 1

    other = client.get("/api/v1/inventory/low-stock?warehouse_id=wh_nonexistent", headers=admin_headers)
    assert other.json()["alerts"] == []


def test_client_role_cannot_list_low_stock_alerts(client, client_headers):
    resp = client.get("/api/v1/inventory/low-stock", headers=client_headers)

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"
