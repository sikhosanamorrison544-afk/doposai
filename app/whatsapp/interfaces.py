"""
WhatsApp service interfaces for future chatbot integration.

Workflow (future):
  Customer → Business WhatsApp → Chatbot → POS API → Quotation Engine
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class WhatsappMessageResult:
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


class WhatsappProvider(ABC):
    """Provider adapter (Meta Cloud API, Twilio, etc.) — not implemented."""

    @abstractmethod
    def send_text(self, to_phone: str, body: str) -> WhatsappMessageResult:
        raise NotImplementedError

    @abstractmethod
    def send_document(self, to_phone: str, document_bytes: bytes, filename: str) -> WhatsappMessageResult:
        raise NotImplementedError


class WhatsappQuotationService(ABC):
    @abstractmethod
    def send_quotation(self, tenant_id: int, quotation_id: int, to_phone: str) -> WhatsappMessageResult:
        raise NotImplementedError


class WhatsappStatementService(ABC):
    @abstractmethod
    def send_customer_statement(self, tenant_id: int, customer_id: int, to_phone: str) -> WhatsappMessageResult:
        raise NotImplementedError


class WhatsappReceiptService(ABC):
    @abstractmethod
    def send_sale_receipt(self, tenant_id: int, sale_id: int, to_phone: str) -> WhatsappMessageResult:
        raise NotImplementedError


class WhatsappPaymentReminderService(ABC):
    @abstractmethod
    def send_payment_reminder(self, tenant_id: int, customer_id: int, to_phone: str) -> WhatsappMessageResult:
        raise NotImplementedError


class WhatsappSupportService(ABC):
    @abstractmethod
    def route_inbound_message(self, tenant_id: int, from_phone: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError


class StubWhatsappProvider(WhatsappProvider):
    """Placeholder until Meta/Twilio integration."""

    def send_text(self, to_phone: str, body: str) -> WhatsappMessageResult:
        return WhatsappMessageResult(
            success=False,
            error="WhatsApp not configured. Set up whatsapp_integrations and provider.",
        )

    def send_document(self, to_phone: str, document_bytes: bytes, filename: str) -> WhatsappMessageResult:
        return self.send_text(to_phone, f"[document: {filename}]")


whatsapp_provider: WhatsappProvider = StubWhatsappProvider()
