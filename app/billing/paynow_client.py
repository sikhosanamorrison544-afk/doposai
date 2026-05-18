"""Paynow Zimbabwe wrapper (EcoCash mobile + web redirect)."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..config import API_PUBLIC_URL

logger = logging.getLogger(__name__)


def _as_optional_str(value: Any) -> Optional[str]:
    """Coerce Paynow SDK fields to strings (some responses expose methods, not text)."""
    if value is None:
        return None
    if callable(value) and not isinstance(value, type):
        try:
            value = value()
        except TypeError:
            return None
    return str(value).strip() or None


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
            raw_data = getattr(response, "data", None) or {}
            err = getattr(response, "error", None)
            if isinstance(raw_data, dict):
                err = err or raw_data.get("error")
            if getattr(response, "success", False):
                return PaynowInitResult(
                    success=True,
                    redirect_url=_as_optional_str(getattr(response, "redirect_url", None)),
                    poll_url=_as_optional_str(
                        getattr(response, "poll_url", None)
                        or (raw_data.get("pollurl") if isinstance(raw_data, dict) else None)
                    ),
                    raw={"reference": reference},
                )
            return PaynowInitResult(
                success=False,
                error=_as_optional_str(err) or "Paynow rejected request",
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
            raw_data = getattr(response, "data", None) or {}
            if isinstance(raw_data, dict):
                poll_url = _as_optional_str(
                    getattr(response, "poll_url", None) or raw_data.get("pollurl")
                )
                instructions = _as_optional_str(
                    getattr(response, "instructions", None)
                    or getattr(response, "instruction", None)
                    or raw_data.get("instructions")
                )
                err = _as_optional_str(
                    getattr(response, "error", None) or raw_data.get("error")
                )
            else:
                poll_url = _as_optional_str(getattr(response, "poll_url", None))
                instructions = _as_optional_str(
                    getattr(response, "instructions", None)
                    or getattr(response, "instruction", None)
                )
                err = _as_optional_str(getattr(response, "error", None))
            if getattr(response, "success", False):
                if not poll_url:
                    return PaynowInitResult(
                        success=False,
                        error="Paynow did not return a poll URL for this EcoCash payment",
                        raw=raw_data if isinstance(raw_data, dict) else None,
                    )
                return PaynowInitResult(
                    success=True,
                    poll_url=poll_url,
                    instructions=instructions,
                    raw={"reference": reference, "phone": phone},
                )
            return PaynowInitResult(
                success=False,
                error=err or "EcoCash request failed",
                raw=raw_data if isinstance(raw_data, dict) else None,
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
        normalized = p
    elif p.startswith("0"):
        normalized = "263" + p[1:]
    elif len(p) == 9:
        normalized = "263" + p
    else:
        normalized = p
    if len(normalized) < 11 or not normalized.startswith("263"):
        raise ValueError(
            "Invalid EcoCash number. Use 0771234567 or 263771234567 format."
        )
    return normalized


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
