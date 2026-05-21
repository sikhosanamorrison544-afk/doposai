"""FastAPI routes for the WhatsApp chatbot.

Public routes
-------------
GET  /whatsapp/webhook    — Meta subscription verification handshake.
POST /whatsapp/webhook    — Inbound message delivery (signed by Meta).

Authenticated routes
--------------------
GET  /api/whatsapp/settings   — current tenant's bot config.
PUT  /api/whatsapp/settings   — admin updates keyword / welcome / enabled.
GET  /api/whatsapp/status     — environment readiness summary (admin).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import auth
from ..database import get_db
from ..models import User
from ..quotation_models import Tenant
from . import config, parser, router, signature, tenant_routing

logger = logging.getLogger(__name__)

webhook_router = APIRouter(prefix="/whatsapp", tags=["whatsapp-webhook"])
api_router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp-admin"])


# ── webhook handshake (GET) ─────────────────────────────────────────────


@webhook_router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_challenge: str = Query("", alias="hub.challenge"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
):
    """Meta will hit this once when you subscribe the webhook.

    We must echo ``hub.challenge`` iff the ``hub.verify_token`` matches
    the value configured in our env (``WHATSAPP_VERIFY_TOKEN``).
    """
    if hub_mode != "subscribe":
        raise HTTPException(status_code=400, detail="unsupported hub.mode")
    if not config.WHATSAPP_VERIFY_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="WHATSAPP_VERIFY_TOKEN not configured on the server",
        )
    if hub_verify_token != config.WHATSAPP_VERIFY_TOKEN:
        # Don't leak which side of the comparison failed.
        raise HTTPException(status_code=403, detail="verify_token mismatch")
    return PlainTextResponse(hub_challenge)


# ── webhook receive (POST) ──────────────────────────────────────────────


@webhook_router.post("/webhook")
async def receive_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
):
    """Process inbound messages from Meta.

    Contract with Meta:
      * MUST return 2xx within ~10s or Meta retries.
      * MUST verify ``X-Hub-Signature-256`` against APP_SECRET (HMAC-SHA256).

    We do the dispatch synchronously for Phase 1 because each message
    only triggers one outbound API call. If latency becomes a problem we
    can move to BackgroundTasks or a queue without changing the contract.
    """
    raw_body = await request.body()

    if not signature.verify_meta_signature(
        raw_body, x_hub_signature_256, config.WHATSAPP_APP_SECRET
    ):
        # 401, not 403 — Meta retries on 5xx but not 4xx, which is what
        # we want when the signature is wrong.
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        envelope = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid json")

    messages = parser.parse_inbound_messages(envelope)
    if not messages:
        # Statuses-only delivery — ack and move on.
        return {"ok": True, "handled": 0}

    handled = 0
    for msg in messages:
        try:
            await router.handle_inbound(db, msg)
            handled += 1
        except Exception:  # noqa: BLE001 — never let one bad msg 500 the webhook
            logger.exception("WhatsApp dispatch failed for msg=%s", msg.wa_message_id)
            db.rollback()

    return {"ok": True, "handled": handled}


# ── per-tenant admin settings ───────────────────────────────────────────


class WhatsAppSettingsRead(BaseModel):
    tenant_id: int
    enabled: bool
    keyword: Optional[str]
    welcome_message: Optional[str]
    business_type: Optional[str]
    business_description: Optional[str]

    class Config:
        from_attributes = True


class WhatsAppSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    keyword: Optional[str] = Field(default=None, max_length=32)
    welcome_message: Optional[str] = Field(default=None, max_length=2000)
    business_type: Optional[str] = Field(default=None, max_length=64)
    business_description: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("keyword")
    @classmethod
    def normalize_kw(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = tenant_routing.normalize_keyword(v)
        if not v:
            return None
        if len(v) < 2:
            raise ValueError("keyword must be at least 2 alphanumeric characters")
        return v


def _require_tenant(current_user: User) -> int:
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This user is not attached to a tenant",
        )
    return current_user.tenant_id


def _tenant_to_settings(t: Tenant) -> WhatsAppSettingsRead:
    return WhatsAppSettingsRead(
        tenant_id=t.id,
        enabled=bool(t.whatsapp_enabled),
        keyword=t.whatsapp_keyword,
        welcome_message=t.whatsapp_welcome_message,
        business_type=t.business_type,
        business_description=t.business_description,
    )


@api_router.get("/settings", response_model=WhatsAppSettingsRead)
async def get_whatsapp_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    tid = _require_tenant(current_user)
    tenant = db.get(Tenant, tid)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    return _tenant_to_settings(tenant)


@api_router.put("/settings", response_model=WhatsAppSettingsRead)
async def update_whatsapp_settings(
    body: WhatsAppSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_admin_user),
):
    tid = _require_tenant(current_user)
    tenant = db.get(Tenant, tid)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")

    if body.enabled is not None:
        tenant.whatsapp_enabled = body.enabled
    if body.welcome_message is not None:
        tenant.whatsapp_welcome_message = body.welcome_message.strip() or None
    if body.business_type is not None:
        tenant.business_type = body.business_type.strip() or None
    if body.business_description is not None:
        tenant.business_description = body.business_description.strip() or None

    if body.keyword is not None:
        new_kw = body.keyword
        if new_kw:
            clash = (
                db.query(Tenant)
                .filter(
                    Tenant.id != tenant.id,
                    func.upper(Tenant.whatsapp_keyword) == new_kw,
                )
                .first()
            )
            if clash:
                raise HTTPException(
                    status_code=409,
                    detail=f"keyword '{new_kw}' is already taken",
                )
        tenant.whatsapp_keyword = new_kw or None

    db.commit()
    db.refresh(tenant)
    return _tenant_to_settings(tenant)


@api_router.get("/status")
async def whatsapp_status(
    current_user: User = Depends(auth.get_current_admin_user),  # noqa: ARG001
):
    return {
        "configured": config.is_configured(),
        "api_version": config.WHATSAPP_API_VERSION,
        "phone_number_id_set": bool(config.WHATSAPP_PHONE_NUMBER_ID),
        "verify_token_set": bool(config.WHATSAPP_VERIFY_TOKEN),
        "access_token_set": bool(config.WHATSAPP_ACCESS_TOKEN),
        "app_secret_set": bool(config.WHATSAPP_APP_SECRET),
        "session_timeout_hours": config.WHATSAPP_SESSION_TIMEOUT_HOURS,
        "brand_name": config.WHATSAPP_BRAND_NAME,
    }
