"""Unit tests for the pure request-hashing logic used by idempotency_service."""
from src.services.idempotency_service import compute_request_hash


def test_hash_is_stable_regardless_of_key_order():
    a = compute_request_hash({"items": [{"product_id": "p1", "quantity": 2}], "payment_token": "success"})
    b = compute_request_hash({"payment_token": "success", "items": [{"product_id": "p1", "quantity": 2}]})
    assert a == b


def test_hash_differs_for_different_payloads():
    a = compute_request_hash({"items": [{"product_id": "p1", "quantity": 1}]})
    b = compute_request_hash({"items": [{"product_id": "p1", "quantity": 2}]})
    assert a != b
