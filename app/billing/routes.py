"""Billing & subscription HTTP API (Paynow / EcoCash)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_active_user, get_current_admin_user
from ..database import get_db
from ..models import User
from ..quotation_models import Tenant
from . import service as billing_service
from .paynow_client import get_paynow_client
from .plans import list_plans_public

logger = logging.getLogger(__name__)

subscriptions_router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])
payments_router = APIRouter(prefix="/api/payments", tags=["payments"])
billing_router = APIRouter(prefix="/api/billing", tags=["billing"])


def _tenant_for_user(db: Session, user: User) -> Tenant:
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="No tenant on this account")
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


class CreateSubscriptionBody(BaseModel):
    plan: str = Field(default="starter", pattern="^(starter|business|pro)$")
    billing_cycle: Optional[str] = Field(default=None, pattern="^(monthly|yearly)$")


class UpgradeBody(BaseModel):
    plan: str = Field(..., pattern="^(starter|business|pro)$")
    billing_cycle: str = Field(..., pattern="^(monthly|yearly)$")
    ecocash_phone: Optional[str] = Field(default=None, max_length=20)


class InitiatePaymentBody(BaseModel):
    plan: str = Field(..., pattern="^(starter|business|pro)$")
    billing_cycle: str = Field(..., pattern="^(monthly|yearly)$")
    ecocash_phone: Optional[str] = Field(default=None, max_length=20)
    channel: str = Field(default="web", max_length=16)


class VerifyPaymentBody(BaseModel):
    payment_reference: str = Field(..., min_length=6, max_length=64)
    poll_url: Optional[str] = None


@subscriptions_router.get("/plans")
def list_plans() -> Dict[str, Any]:
    return {"plans": list_plans_public(), "paynow_configured": get_paynow_client().is_configured()}


@subscriptions_router.post("/create")
def create_subscription(
    body: CreateSubscriptionBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant = _tenant_for_user(db, user)
    sub = billing_service.get_or_create_subscription(db, tenant)
    if body.plan:
        sub.plan = body.plan
    if body.billing_cycle:
        sub.billing_cycle = body.billing_cycle
    if sub.status not in ("active", "pending_payment"):
        billing_service.create_trial_subscription(db, tenant)
    db.commit()
    return billing_service.subscription_status_payload(db, tenant)


@subscriptions_router.post("/upgrade")
def upgrade_subscription(
    body: UpgradeBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant = _tenant_for_user(db, user)
    email = (user.email or tenant.email or "").strip()
    if body.ecocash_phone and not email:
        raise HTTPException(
            status_code=400,
            detail="Set a valid email on your admin account before paying with EcoCash.",
        )
    try:
        payload = billing_service.upgrade_subscription(
            db,
            tenant,
            body.plan,
            body.billing_cycle,
            email,
            body.ecocash_phone,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return payload


@subscriptions_router.post("/cancel")
def cancel_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant = _tenant_for_user(db, user)
    return billing_service.cancel_subscription(db, tenant)


@subscriptions_router.get("/status")
def subscription_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    tenant = _tenant_for_user(db, user)
    return billing_service.subscription_status_payload(db, tenant)


@payments_router.post("/initiate")
def initiate_payment(
    body: InitiatePaymentBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant = _tenant_for_user(db, user)
    email = (user.email or tenant.email or "").strip()
    if body.ecocash_phone and not email:
        raise HTTPException(
            status_code=400,
            detail="Set a valid email on your admin account before paying with EcoCash.",
        )
    try:
        _, payload = billing_service.start_pending_payment(
            db,
            tenant,
            email,
            body.plan,
            body.billing_cycle,
            ecocash_phone=body.ecocash_phone,
            channel=body.channel,
        )
        db.commit()
        return payload
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@payments_router.post("/verify")
def verify_payment(
    body: VerifyPaymentBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant = _tenant_for_user(db, user)
    try:
        return billing_service.verify_and_apply_payment(
            db, tenant, body.payment_reference, poll_url=body.poll_url
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@payments_router.post("/webhook")
async def paynow_webhook(request: Request, db: Session = Depends(get_db)) -> Dict[str, str]:
    """
    Paynow result URL (server-to-server). Never trust client redirects alone.
  """
    content_type = (request.headers.get("content-type") or "").lower()
    form: Dict[str, str] = {}
    if "application/json" in content_type:
        try:
            data = await request.json()
            form = {str(k): str(v) for k, v in data.items()}
        except Exception:
            form = {}
    else:
        body = await request.body()
        if body:
            from urllib.parse import parse_qs

            parsed = parse_qs(body.decode("utf-8", errors="replace"))
            form = {k: (v[0] if v else "") for k, v in parsed.items()}
        else:
            try:
                raw = await request.form()
                form = {k: str(raw.get(k) or "") for k in raw.keys()}
            except Exception:
                form = {}

    logger.info("Paynow webhook reference=%s status=%s", form.get("reference"), form.get("status"))
    return billing_service.process_paynow_webhook(db, form)


@billing_router.get("/health")
def billing_health() -> Dict[str, Any]:
    from ..config import TRIAL_DAYS_DEFAULT

    pn = get_paynow_client()
    return {
        "ok": True,
        "trial_days_default": TRIAL_DAYS_DEFAULT,
        "paynow_configured": pn.is_configured(),
        "return_url": pn.return_url,
        "result_url": pn.result_url,
    }


@billing_router.get("/history")
def billing_history(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant = _tenant_for_user(db, user)
    return billing_service.billing_history(db, tenant.id)
