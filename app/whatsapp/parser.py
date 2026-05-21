"""Translate the Meta webhook envelope into ``InboundMessage`` objects.

Meta nests messages a few layers deep:

    body.entry[].changes[].value.messages[]

Each ``messages[]`` entry can be a text, interactive (button/list reply),
button click on a template, image, document, etc. We normalize only what
the Phase-1 router needs — everything else gets an empty ``text`` and
``raw`` preserved for debugging.
"""
from __future__ import annotations

from typing import Iterable, List

from .router import InboundMessage


def parse_inbound_messages(envelope: dict) -> List[InboundMessage]:
    """Walk the Meta webhook payload, yield one InboundMessage per message.

    Status callbacks (``statuses[]``) are ignored — they're delivery
    receipts, not customer messages.
    """
    out: List[InboundMessage] = []
    entries: Iterable[dict] = envelope.get("entry") or []
    for entry in entries:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for raw_msg in value.get("messages") or []:
                msg = _parse_one(raw_msg)
                if msg is not None:
                    out.append(msg)
    return out


def _parse_one(raw: dict) -> InboundMessage | None:
    sender = (raw.get("from") or "").strip()
    if not sender:
        return None

    mtype = raw.get("type") or "unknown"
    wa_id = raw.get("id")
    text = ""
    interactive_id: str | None = None

    if mtype == "text":
        text = ((raw.get("text") or {}).get("body") or "").strip()
    elif mtype == "interactive":
        inter = raw.get("interactive") or {}
        inter_type = inter.get("type")
        if inter_type == "list_reply":
            reply = inter.get("list_reply") or {}
            interactive_id = reply.get("id") or None
            text = (reply.get("title") or "").strip()
        elif inter_type == "button_reply":
            reply = inter.get("button_reply") or {}
            interactive_id = reply.get("id") or None
            text = (reply.get("title") or "").strip()
    elif mtype == "button":
        btn = raw.get("button") or {}
        text = (btn.get("text") or "").strip()
        interactive_id = btn.get("payload")
    elif mtype in {"image", "document", "audio", "video", "sticker", "location"}:
        text = ""
    else:
        text = ""

    return InboundMessage(
        from_phone=sender,
        wa_message_id=wa_id,
        message_type=mtype,
        text=text,
        interactive_id=interactive_id,
        raw=raw,
    )
