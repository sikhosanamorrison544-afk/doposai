"""Thin async wrapper around the WhatsApp Cloud API send endpoints.

All public functions return a ``SendResult`` describing whether the call
succeeded, the wa_message_id Meta assigned, and (on failure) a short
human-readable error suitable for storing in the audit log.

Network usage is deliberately conservative:
  * Short timeouts (10s connect, 15s read) so the webhook never hangs.
  * One process-wide httpx.AsyncClient created lazily.
  * Errors are swallowed to a SendResult — never raise into webhook code.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence

import httpx

from . import config

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = httpx.AsyncClient(timeout=_TIMEOUT)
    return _client


async def shutdown() -> None:
    """Close the shared client; call from app shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


@dataclass
class SendResult:
    ok: bool
    wa_message_id: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[dict] = None


def _messages_url() -> str:
    return f"{config.graph_base_url()}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _normalize_msisdn(to: str) -> str:
    """Meta expects digits only, no leading '+'."""
    return "".join(ch for ch in to if ch.isdigit())


async def _post(payload: dict) -> SendResult:
    if not config.is_configured():
        return SendResult(ok=False, error="WhatsApp not configured (missing env vars)")
    try:
        client = await _get_client()
        resp = await client.post(
            _messages_url(), headers=_auth_headers(), json=payload
        )
    except httpx.HTTPError as exc:
        logger.warning("WhatsApp send transport error: %s", exc)
        return SendResult(ok=False, error=f"transport: {exc!s}"[:240])

    data: Optional[dict] = None
    try:
        data = resp.json()
    except ValueError:
        data = None

    if resp.status_code >= 400:
        err_msg = ""
        if data and isinstance(data.get("error"), dict):
            err = data["error"]
            err_msg = f"{err.get('code')}: {err.get('message')}"
        else:
            err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
        logger.warning("WhatsApp send failed: %s", err_msg)
        return SendResult(ok=False, error=err_msg[:240], raw=data)

    wa_id = None
    if data and isinstance(data.get("messages"), list) and data["messages"]:
        wa_id = data["messages"][0].get("id")
    return SendResult(ok=True, wa_message_id=wa_id, raw=data)


# ── send helpers ────────────────────────────────────────────────────────


async def send_text(to: str, body: str, preview_url: bool = False) -> SendResult:
    payload = {
        "messaging_product": "whatsapp",
        "to": _normalize_msisdn(to),
        "type": "text",
        "text": {"body": body[:4096], "preview_url": preview_url},
    }
    return await _post(payload)


@dataclass
class ListRow:
    id: str
    title: str
    description: Optional[str] = None


@dataclass
class ListSection:
    title: str
    rows: Sequence[ListRow]


async def send_list(
    to: str,
    body_text: str,
    button_text: str,
    sections: Iterable[ListSection],
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
) -> SendResult:
    """Send an interactive list message (preferred for the business menu)."""
    section_payload: List[dict] = []
    for sec in sections:
        section_payload.append(
            {
                "title": sec.title[:24],
                "rows": [
                    {
                        "id": row.id[:200],
                        "title": row.title[:24],
                        **({"description": row.description[:72]} if row.description else {}),
                    }
                    for row in sec.rows
                ],
            }
        )

    interactive: dict = {
        "type": "list",
        "body": {"text": body_text[:1024]},
        "action": {"button": button_text[:20], "sections": section_payload},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text[:60]}
    if footer_text:
        interactive["footer"] = {"text": footer_text[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "to": _normalize_msisdn(to),
        "type": "interactive",
        "interactive": interactive,
    }
    return await _post(payload)


@dataclass
class ReplyButton:
    id: str
    title: str


async def send_buttons(
    to: str,
    body_text: str,
    buttons: Sequence[ReplyButton],
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
) -> SendResult:
    """Send up to 3 quick-reply buttons. Anything more should use send_list."""
    btn_payload = [
        {"type": "reply", "reply": {"id": b.id[:256], "title": b.title[:20]}}
        for b in buttons[:3]
    ]
    interactive: dict[str, Any] = {
        "type": "button",
        "body": {"text": body_text[:1024]},
        "action": {"buttons": btn_payload},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text[:60]}
    if footer_text:
        interactive["footer"] = {"text": footer_text[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "to": _normalize_msisdn(to),
        "type": "interactive",
        "interactive": interactive,
    }
    return await _post(payload)
