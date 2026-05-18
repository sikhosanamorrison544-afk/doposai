"""Paynow Zimbabwe wrapper (EcoCash mobile + web redirect)."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..config import API_PUBLIC_URL

logger = logging.getLogger(__name__)


@dataclass
class PaynowInitResult:
    success: bool
    redirect_url: Optional[str] = None
    poll_url: Optional[str] = None
    instructions: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass
class PaynowStatusResult:
    paid: bool
    status: str
    reference: Optional[str] = None
    paynow_reference: Optional[str] = None
    amount: Optional[float] = None
    raw: Optional[Any] = None


class PaynowClient:
    def __init__(self) -> None:
        self.integration_id = os.environ.get("PAYNOW_INTEGRATION_ID", "").strip()
        self.integration_key = os.environ.get("PAYNOW_INTEGRATION_KEY", "").strip()
        self.return_url = os.environ.get(
            "PAYNOW_RETURN_URL",
            f"{API_PUBLIC_URL}/billing?payment=return",
        ).strip()
        self.result_url = os.environ.get(
            "PAYNOW_RESULT_URL",
            f"{API_PUBLIC_URL}/api/payments/webhook",
        ).strip()
        self._sdk = None

    def is_configured(self) -> bool:
        return bool(self.integration_id and self.integration_key)

    def _client(self):
        if self._sdk is not None:
            return self._sdk
        if not self.is_configured():
            raise RuntimeError("Paynow is not configured (missing integration id/key)")
        try:
            from paynow import Paynow
        except ImportError as e:
            raise RuntimeError("paynow package not installed") from e
        self._sdk = Paynow(
            self.integration_id,
            self.integration_key,
            self.return_url,
            self.result_url,
        )
        return self._sdk

    def initiate_web(
        self,
        reference: str,
        email: str,
        amount: float,
        description: str,
    ) -> PaynowInitResult:
        try:
            paynow = self._client()
            payment = paynow.create_payment(reference, email)
            payment.add(description[:100], float(f"{amount:.2f}"))
            response = paynow.send(payment)
            if getattr(response, "success", False):
                return PaynowInitResult(
                    success=True,
                    redirect_url=getattr(response, "redirect_url", None),
                    poll_url=getattr(response, "poll_url", None),
                    raw={"reference": reference},
                )
            return PaynowInitResult(
                success=False,
                error=str(getattr(response, "error", None) or "Paynow rejected request"),
            )
        except Exception as e:
            logger.exception("Paynow web initiate failed")
            return PaynowInitResult(success=False, error=str(e))

    def initiate_ecocash(
        self,
        reference: str,
        email: str,
        amount: float,
        description: str,
        phone: str,
    ) -> PaynowInitResult:
        """Express checkout — EcoCash STK-style flow on user's phone."""
        phone = _normalize_phone(phone)
        try:
            paynow = self._client()
            payment = paynow.create_payment(reference, email)
            payment.add(description[:100], float(f"{amount:.2f}"))
            response = paynow.send_mobile(payment, phone, "ecocash")
            if getattr(response, "success", False):
                return PaynowInitResult(
                    success=True,
                    poll_url=getattr(response, "poll_url", None),
                    instructions=getattr(response, "instructions", None),
                    raw={"reference": reference, "phone": phone},
                )
            return PaynowInitResult(
                success=False,
                error=str(getattr(response, "error", None) or "EcoCash request failed"),
            )
        except Exception as e:
            logger.exception("Paynow EcoCash initiate failed")
            return PaynowInitResult(success=False, error=str(e))

    def poll_status(self, poll_url: str) -> PaynowStatusResult:
        try:
            paynow = self._client()
            status = paynow.check_transaction_status(poll_url)
            paid = bool(getattr(status, "paid", False))
            st = str(getattr(status, "status", "") or "").lower()
            return PaynowStatusResult(
                paid=paid or st == "paid",
                status=st or ("paid" if paid else "unknown"),
                reference=getattr(status, "reference", None),
                paynow_reference=getattr(status, "paynowreference", None),
                amount=_safe_float(getattr(status, "amount", None)),
                raw=status,
            )
        except Exception as e:
            logger.exception("Paynow poll failed")
            return PaynowStatusResult(paid=False, status="error", raw=str(e))


def _normalize_phone(phone: str) -> str:
    p = "".join(c for c in (phone or "") if c.isdigit())
    if p.startswith("263"):
        return p
    if p.startswith("0"):
        return "263" + p[1:]
    if len(p) == 9:
        return "263" + p
    return p


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


_paynow_singleton: Optional[PaynowClient] = None


def get_paynow_client() -> PaynowClient:
    global _paynow_singleton
    if _paynow_singleton is None:
        _paynow_singleton = PaynowClient()
    return _paynow_singleton
