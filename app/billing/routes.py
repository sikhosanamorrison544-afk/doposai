"""Billing & subscription HTTP surface — webhooks and checkout stubs."""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Request, status

from ..config import BILLING_WEBHOOK_SECRET, TRIAL_DAYS_DEFAULT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/health")
def billing_health() -> Dict[str, Any]:
    return {
        "ok": True,
        "trial_days_default": TRIAL_DAYS_DEFAULT,
        "webhook_configured": bool(BILLING_WEBHOOK_SECRET),
        "message": "Payment capture not implemented — use this router for Paynow/EcoCash webhooks later.",
    }


@router.post("/webhook/payment")
async def payment_webhook_placeholder(
    request: Request,
    x_signature: str | None = Header(default=None, alias="X-Signature"),
) -> Dict[str, str]:
    """
    Future: verify HMAC with BILLING_WEBHOOK_SECRET, idempotency key, update tenant subscription in Postgres + Firestore.
    """
    body = await request.body()
    if BILLING_WEBHOOK_SECRET and not x_signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing signature")
    logger.info("billing webhook received (%s bytes), signature=%s", len(body), bool(x_signature))
    return {"status": "ignored", "detail": "Webhook handler not implemented"}
