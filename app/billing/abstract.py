"""Payment / subscription abstraction — wire Paynow, EcoCash, Stripe later."""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol


class PaymentProvider(Protocol):
    """Future: Paynow, EcoCash, card gateway."""

    name: str

    def create_checkout_session(
        self,
        tenant_uid: str,
        amount_cents: int,
        currency: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        ...

    def verify_webhook(self, payload: bytes, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
        ...


class NoOpPaymentProvider:
    name = "noop"

    def create_checkout_session(self, tenant_uid: str, amount_cents: int, currency: str, metadata: Dict[str, Any]):
        return {"url": None, "status": "not_configured"}

    def verify_webhook(self, payload: bytes, headers: Dict[str, str]):
        return None


def get_payment_provider() -> PaymentProvider:
    """Resolve active provider from env (future)."""
    return NoOpPaymentProvider()  # type: ignore[return-value]
