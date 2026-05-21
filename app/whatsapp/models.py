"""WhatsApp chatbot persistence models.

These power the multi-tenant routing layer that sits on top of a single
WhatsApp Cloud API number. The state machine reads/writes WhatsAppSession
rows keyed by customer phone; all inbound and outbound traffic is also
logged into WhatsAppMessage for auditing and replay.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class WhatsAppSession(Base):
    """One row per customer phone (E.164 without leading +).

    `current_state` values:
        - "menu"       — awaiting business selection
        - "in_business"— selected_tenant_id set; messages dispatched to that tenant
        - "handover"   — bot paused; waiting for human agent
    """

    __tablename__ = "whatsapp_sessions"

    phone_number: Mapped[str] = mapped_column(String(32), primary_key=True)
    selected_tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    current_state: Mapped[str] = mapped_column(
        String(24), default="menu", nullable=False
    )
    last_activity: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True
    )
    last_menu_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_handover_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WhatsAppMessage(Base):
    """Audit log for every inbound and outbound message handled by the
    Phase-1 chatbot router.

    NOTE: the table name is ``whatsapp_chatbot_messages`` (not the more
    obvious ``whatsapp_messages``) because the latter already exists in
    legacy deployments from an earlier prototype with a totally different
    schema. The ``WhatsAppMessage`` class name is kept short for ergonomics.
    """

    __tablename__ = "whatsapp_chatbot_messages"
    __table_args__ = (
        Index("ix_wacmsg_phone_created", "customer_phone", "created_at"),
        Index("ix_wacmsg_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    customer_phone: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # "in" | "out"
    message_type: Mapped[str] = mapped_column(String(24), default="text", nullable=False)
    wa_message_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
