"""Unit tests for the deterministic simulated payment provider (PRD section 10)."""
from src.models.enums import PaymentResult
from src.services import payment_service


def test_success_token_succeeds():
    outcome = payment_service.charge("success")
    assert outcome.result == PaymentResult.SUCCESS


def test_fail_token_fails_permanently():
    outcome = payment_service.charge("fail")
    assert outcome.result == PaymentResult.FAILED
    assert outcome.retryable is False


def test_fail_retryable_token_fails_but_is_retryable():
    outcome = payment_service.charge("fail_retryable")
    assert outcome.result == PaymentResult.FAILED
    assert outcome.retryable is True


def test_unknown_token_defaults_to_success():
    outcome = payment_service.charge("something-a-client-made-up")
    assert outcome.result == PaymentResult.SUCCESS
