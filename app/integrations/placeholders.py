"""Placeholder integrations — implement later (WhatsApp, remote Ollama on Hetzner)."""
from __future__ import annotations

from typing import Any, Dict, Protocol


class WhatsAppNotifier(Protocol):
    def send_template(self, to_e164: str, template: str, params: Dict[str, Any]) -> bool: ...


class NoOpWhatsApp:
    def send_template(self, to_e164: str, template: str, params: Dict[str, Any]) -> bool:
        return False


def get_whatsapp() -> WhatsAppNotifier:
    return NoOpWhatsApp()  # type: ignore[return-value]


class RemoteAIClient(Protocol):
    def summarize(self, text: str) -> str: ...


class NoOpRemoteAI:
    def summarize(self, text: str) -> str:
        return ""
