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
    """Resolve active provider from env."""
    from .paynow_client import get_paynow_client

    if get_paynow_client().is_configured():
        return PaynowProviderAdapter()  # type: ignore[return-value]
    return NoOpPaymentProvider()  # type: ignore[return-value]


class PaynowProviderAdapter:
    name = "paynow"

    def create_checkout_session(
        self, tenant_uid: str, amount_cents: int, currency: str, metadata: dict
    ):
        from .paynow_client import get_paynow_client

        amount = amount_cents / 100.0
        ref = metadata.get("reference", tenant_uid)
        email = metadata.get("email", "billing@tenant.local")
        desc = metadata.get("description", "Subscription")
        phone = metadata.get("ecocash_phone")
        client = get_paynow_client()
        if phone:
            r = client.initiate_ecocash(ref, email, amount, desc, phone)
        else:
            r = client.initiate_web(ref, email, amount, desc)
        return {
            "url": r.redirect_url,
            "poll_url": r.poll_url,
            "instructions": r.instructions,
            "success": r.success,
            "error": r.error,
        }

    def verify_webhook(self, payload: bytes, headers: dict):
        return None
