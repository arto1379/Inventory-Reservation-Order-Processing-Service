"""
Simulated payment provider (PRD section 10, out-of-scope: real payment
integration). Behaviour is fully deterministic based on the order's
`payment_token`, so tests can exercise every order-processing branch
without any network calls or randomness:

    "success"        -> succeeds immediately.
    "fail"            -> fails immediately and permanently (no retry).
    "fail_retryable"  -> fails with a *transient* error every attempt; the
                         order worker retries it with exponential backoff
                         (Bonus A) until PAYMENT_MAX_ATTEMPTS is reached,
                         at which point it becomes a permanent FAILED order.

Any other token value is treated as "success" so ad-hoc manual testing via
the API (where most callers won't set a token at all) behaves intuitively.
"""
from dataclasses import dataclass

from src.models.enums import PaymentResult

TOKEN_FAIL_PERMANENT = "fail"
TOKEN_FAIL_RETRYABLE = "fail_retryable"


@dataclass(frozen=True)
class PaymentOutcome:
    result: PaymentResult
    retryable: bool
    message: str


def charge(payment_token: str) -> PaymentOutcome:
    """Simulate charging a payment method. Pure function, no I/O -- easy to
    unit test and safe to call repeatedly (retries) without side effects."""
    if payment_token == TOKEN_FAIL_PERMANENT:
        return PaymentOutcome(PaymentResult.FAILED, retryable=False, message="Simulated payment declined")
    if payment_token == TOKEN_FAIL_RETRYABLE:
        return PaymentOutcome(
            PaymentResult.FAILED, retryable=True, message="Simulated transient payment provider error"
        )
    return PaymentOutcome(PaymentResult.SUCCESS, retryable=False, message="Simulated payment approved")
