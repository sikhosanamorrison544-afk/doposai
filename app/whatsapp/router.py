"""Inbound message dispatcher / state machine.

Plain-Python coroutine that takes a parsed inbound message envelope and
emits zero-or-more outbound replies via the Meta client. It also persists
session state and the audit log row for every message it handles.

The dispatcher is intentionally single-threaded per phone number: each
inbound call commits before returning, so concurrent webhook deliveries
for the same customer can't race on session state (the worst case is a
duplicate outbound reply, never a corrupted state).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from ..quotation_models import Tenant
from . import config, meta_client, product_search, tenant_routing
from .meta_client import ListSection
from .models import WhatsAppMessage, WhatsAppSession

logger = logging.getLogger(__name__)

# ── state constants ────────────────────────────────────────────────────

STATE_MENU = "menu"
STATE_IN_BUSINESS = "in_business"
STATE_HANDOVER = "handover"

# ── command keywords (case-insensitive, whole-word match) ──────────────

_RESET_CMDS = {"MENU", "RESET", "BACK", "SWITCH", "CHANGE"}
_HANDOVER_CMDS = {"AGENT", "HUMAN", "SUPPORT", "HELP"}
_STOP_CMDS = {"STOP", "UNSUBSCRIBE"}


@dataclass
class InboundMessage:
    """Normalized view of a single inbound WhatsApp message.

    Only the fields the router cares about — keeps the parser → router
    contract small and easy to test.
    """

    from_phone: str
    wa_message_id: Optional[str]
    message_type: str  # "text" | "interactive" | "image" | etc.
    text: str  # for interactive, the row id or button id; for text, body
    interactive_id: Optional[str] = None  # tenant:42 etc.
    raw: Optional[dict] = None


# ── send-and-log helpers ────────────────────────────────────────────────


def _log_outbound(
    db: Session,
    *,
    tenant_id: Optional[int],
    to: str,
    message_type: str,
    body: str,
    result: meta_client.SendResult,
) -> None:
    db.add(
        WhatsAppMessage(
            tenant_id=tenant_id,
            customer_phone=to,
            direction="out",
            message_type=message_type,
            wa_message_id=result.wa_message_id,
            body=body[:8000],
            payload=result.raw,
            error=result.error,
        )
    )


async def _send_text_and_log(
    db: Session,
    *,
    tenant_id: Optional[int],
    to: str,
    body: str,
) -> meta_client.SendResult:
    result = await meta_client.send_text(to, body)
    _log_outbound(
        db,
        tenant_id=tenant_id,
        to=to,
        message_type="text",
        body=body,
        result=result,
    )
    return result


async def _send_list_and_log(
    db: Session,
    *,
    tenant_id: Optional[int],
    to: str,
    body_text: str,
    button_text: str,
    sections: List[ListSection],
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
) -> meta_client.SendResult:
    result = await meta_client.send_list(
        to,
        body_text=body_text,
        button_text=button_text,
        sections=sections,
        header_text=header_text,
        footer_text=footer_text,
    )
    _log_outbound(
        db,
        tenant_id=tenant_id,
        to=to,
        message_type="interactive_list",
        body=body_text,
        result=result,
    )
    return result


# ── session helpers -----------------------------------------------------


def _get_or_create_session(db: Session, phone: str) -> WhatsAppSession:
    session = db.get(WhatsAppSession, phone)
    if session is None:
        session = WhatsAppSession(
            phone_number=phone,
            current_state=STATE_MENU,
            last_menu_at=datetime.utcnow(),
        )
        db.add(session)
        db.flush()
    return session


def _is_expired(session: WhatsAppSession) -> bool:
    if not session.last_activity:
        return False
    ttl = timedelta(hours=max(1, config.WHATSAPP_SESSION_TIMEOUT_HOURS))
    return datetime.utcnow() - session.last_activity > ttl


def _command_in(text: str, cmds: set[str]) -> bool:
    tokens = {tok.upper() for tok in text.replace(",", " ").split() if tok}
    return bool(tokens & cmds)


# ── outbound message helpers --------------------------------------------


async def _send_welcome_menu(db: Session, to: str) -> None:
    tenants = tenant_routing.active_tenants(db)
    text_fallback = tenant_routing.build_text_menu(config.WHATSAPP_BRAND_NAME, tenants)

    if not tenants:
        await _send_text_and_log(db, tenant_id=None, to=to, body=text_fallback)
        return

    sections, body = tenant_routing.build_list_sections(tenants)
    result = await _send_list_and_log(
        db,
        tenant_id=None,
        to=to,
        body_text=body,
        button_text="Choose business",
        sections=sections,
        header_text=config.WHATSAPP_BRAND_NAME[:60],
        footer_text="Or type a keyword (e.g. GLASS)",
    )
    if not result.ok:
        # Fallback to plain text when list isn't accepted (rare — e.g. on
        # very old client versions or when the number tier blocks lists).
        await _send_text_and_log(db, tenant_id=None, to=to, body=text_fallback)


async def _send_business_welcome(db: Session, to: str, tenant: Tenant) -> None:
    welcome = (
        (tenant.whatsapp_welcome_message or "").strip()
        or (
            f"You're now chatting with {tenant.name}. "
            "Ask about a product (e.g. \"5mm clear glass\"), "
            "type AGENT to talk to a human, or MENU to switch business."
        )
    )
    await _send_text_and_log(db, tenant_id=tenant.id, to=to, body=welcome)


# ── main dispatcher -----------------------------------------------------


async def handle_inbound(db: Session, msg: InboundMessage) -> None:
    """Process one inbound message. Always commits before returning."""
    phone = msg.from_phone

    # 1. audit-log the inbound first, regardless of what happens next
    db.add(
        WhatsAppMessage(
            tenant_id=None,  # backfilled below once tenant is known
            customer_phone=phone,
            direction="in",
            message_type=msg.message_type,
            wa_message_id=msg.wa_message_id,
            body=(msg.text or "")[:8000],
            payload=msg.raw,
        )
    )

    session = _get_or_create_session(db, phone)
    expired = _is_expired(session)

    # 2. STOP / opt-out short-circuit (Meta policy)
    if _command_in(msg.text, _STOP_CMDS):
        session.current_state = STATE_MENU
        session.selected_tenant_id = None
        session.last_activity = datetime.utcnow()
        db.commit()
        await _send_text_and_log(
            db,
            tenant_id=None,
            to=phone,
            body="You're unsubscribed. Send any message to start again.",
        )
        db.commit()
        return

    # 3. interactive list reply: tenant:<id>
    if msg.interactive_id and msg.interactive_id.startswith("tenant:"):
        try:
            tid = int(msg.interactive_id.split(":", 1)[1])
        except (ValueError, IndexError):
            tid = 0
        tenant = tenant_routing.find_tenant_by_id(db, tid) if tid else None
        if tenant:
            session.selected_tenant_id = tenant.id
            session.current_state = STATE_IN_BUSINESS
            session.last_activity = datetime.utcnow()
            db.commit()
            await _send_business_welcome(db, phone, tenant)
            db.commit()
            return

    # 4. explicit reset commands
    if _command_in(msg.text, _RESET_CMDS):
        session.current_state = STATE_MENU
        session.selected_tenant_id = None
        session.last_menu_at = datetime.utcnow()
        session.last_activity = datetime.utcnow()
        db.commit()
        await _send_welcome_menu(db, phone)
        db.commit()
        return

    # 5. expired session → reset, fall through to menu
    if expired and session.current_state == STATE_IN_BUSINESS:
        session.current_state = STATE_MENU
        session.selected_tenant_id = None

    # 6. branch on state
    if session.current_state == STATE_MENU or session.selected_tenant_id is None:
        await _handle_menu(db, session, msg)
    else:
        await _handle_in_business(db, session, msg)


# ── state handlers ------------------------------------------------------


async def _handle_menu(
    db: Session, session: WhatsAppSession, msg: InboundMessage
) -> None:
    phone = session.phone_number
    text = (msg.text or "").strip()

    # numeric pick (1, 2, 3...)
    if text.isdigit():
        tenant = tenant_routing.find_tenant_by_index(db, int(text))
        if tenant:
            session.selected_tenant_id = tenant.id
            session.current_state = STATE_IN_BUSINESS
            session.last_activity = datetime.utcnow()
            db.commit()
            await _send_business_welcome(db, phone, tenant)
            db.commit()
            return

    # keyword
    tenant = tenant_routing.find_tenant_by_keyword(db, text)
    if tenant:
        session.selected_tenant_id = tenant.id
        session.current_state = STATE_IN_BUSINESS
        session.last_activity = datetime.utcnow()
        db.commit()
        await _send_business_welcome(db, phone, tenant)
        db.commit()
        return

    # no match → (re-)send menu
    session.last_activity = datetime.utcnow()
    session.last_menu_at = datetime.utcnow()
    db.commit()
    await _send_welcome_menu(db, phone)
    db.commit()


async def _handle_in_business(
    db: Session, session: WhatsAppSession, msg: InboundMessage
) -> None:
    phone = session.phone_number
    text = (msg.text or "").strip()

    # human handover
    if _command_in(text, _HANDOVER_CMDS):
        session.current_state = STATE_HANDOVER
        session.last_handover_at = datetime.utcnow()
        session.last_activity = datetime.utcnow()
        db.commit()
        notice = config.WHATSAPP_HUMAN_HANDOVER_NOTICE
        await _send_text_and_log(
            db,
            tenant_id=session.selected_tenant_id,
            to=phone,
            body=notice,
        )
        db.commit()
        return

    # handover state: bot silent until customer types RESET / MENU
    if session.current_state == STATE_HANDOVER:
        session.last_activity = datetime.utcnow()
        db.commit()
        return

    # product search
    assert session.selected_tenant_id is not None
    tenant = tenant_routing.find_tenant_by_id(db, session.selected_tenant_id)
    if tenant is None:
        # tenant was disabled mid-session — kick back to menu
        session.current_state = STATE_MENU
        session.selected_tenant_id = None
        db.commit()
        await _send_welcome_menu(db, phone)
        db.commit()
        return

    results: List = product_search.search_products(db, tenant.id, text)
    reply = product_search.format_results(results, tenant.name)
    session.last_activity = datetime.utcnow()
    db.commit()

    await _send_text_and_log(db, tenant_id=tenant.id, to=phone, body=reply)
    db.commit()
