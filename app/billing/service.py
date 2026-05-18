"""Subscription lifecycle, Paynow activation, Firestore sync."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..config import OFFLINE_GRACE_HOURS_DEFAULT, TRIAL_DAYS_DEFAULT
from ..firestore_service import append_billing_event, sync_subscription_firestore
from ..quotation_models import Tenant
from .models import BillingLog, Subscription, SubscriptionPayment
from .paynow_client import PaynowClient, get_paynow_client
from .plans import VALID_PLANS, VALID_STATUSES, get_price

logger = logging.getLogger(__name__)


def _log(db: Session, tenant_id: int, event_type: str, description: str) -> None:
    db.add(BillingLog(tenant_id=tenant_id, event_type=event_type, description=description))


def get_or_create_subscription(db: Session, tenant: Tenant) -> Subscription:
    sub = db.query(Subscription).filter(Subscription.tenant_id == tenant.id).first()
    if sub:
        return sub
    now = datetime.utcnow()
    trial_end = tenant.trial_ends_at or (now + timedelta(days=TRIAL_DAYS_DEFAULT))
    sub = Subscription(
        tenant_id=tenant.id,
        plan="starter",
        billing_cycle=None,
        status=tenant.subscription_status or "trial",
        trial_start=now,
        trial_end=trial_end,
    )
    db.add(sub)
    db.flush()
    _log(db, tenant.id, "subscription_created", "Initial subscription row created")
    return sub


def effective_status(
    sub: Subscription,
    tenant: Optional[Tenant] = None,
    grace_hours: int = OFFLINE_GRACE_HOURS_DEFAULT,
) -> Tuple[str, bool, Optional[datetime]]:
    """
    Returns (status_for_client, access_allowed, subscription_end_or_trial_end).
    access_allowed uses offline grace after last verification.
    """
    now = datetime.utcnow()
    grace = timedelta(hours=grace_hours)

    if sub.status == "suspended":
        return "suspended", False, sub.subscription_end or sub.trial_end

    if sub.status == "pending_payment":
        # Still allow POS during pending EcoCash (short window)
        return "pending_payment", True, sub.subscription_end or sub.trial_end

    if sub.status == "trial":
        end = sub.trial_end
        if end and now <= end:
            return "trial", True, end
        if end and now <= end + grace:
            return "trial_expired", True, end  # grace period
        return "trial_expired", False, end

    if sub.status == "active":
        end = sub.subscription_end
        if not end or now <= end:
            return "active", True, end
        if now <= end + grace:
            return "expired", True, end  # offline-friendly grace
        return "expired", False, end

    if sub.status == "expired":
        end = sub.subscription_end or sub.trial_end
        if tenant and tenant.last_subscription_verified_at:
            if now <= tenant.last_subscription_verified_at + grace:
                return "expired", True, end
        return "expired", False, end

    return sub.status or "trial", True, sub.trial_end


def _days_remaining(end_at: Optional[datetime]) -> Optional[int]:
    if not end_at:
        return None
    delta = end_at - datetime.utcnow()
    return max(0, int(delta.total_seconds() // 86400))


def subscription_status_payload(db: Session, tenant: Tenant) -> Dict[str, Any]:
    sub = get_or_create_subscription(db, tenant)
    status, allowed, ends = effective_status(sub, tenant)
    trial_end = sub.trial_end
    sub_end = sub.subscription_end
    days_trial = _days_remaining(trial_end) if trial_end else None
    days_sub = _days_remaining(sub_end) if sub_end else None
    if sub.status == "active" and sub_end:
        days_remaining = days_sub
    elif trial_end and status in ("trial", "trial_expired", "pending_payment", "expired"):
        days_remaining = days_trial
    elif sub_end:
        days_remaining = days_sub
    else:
        days_remaining = None
    return {
        "tenant_id": tenant.id,
        "tenant_uid": tenant.tenant_uid,
        "plan": sub.plan,
        "billing_cycle": sub.billing_cycle,
        "status": sub.status,
        "effective_status": status,
        "access_allowed": allowed,
        "trial_start": sub.trial_start.isoformat() + "Z" if sub.trial_start else None,
        "trial_end": sub.trial_end.isoformat() + "Z" if sub.trial_end else None,
        "subscription_start": sub.subscription_start.isoformat() + "Z" if sub.subscription_start else None,
        "subscription_end": sub.subscription_end.isoformat() + "Z" if sub.subscription_end else None,
        "days_remaining": days_remaining,
        "days_remaining_trial": days_trial,
        "days_remaining_subscription": days_sub,
        "last_verified_at": (
            tenant.last_subscription_verified_at.isoformat() + "Z"
            if tenant.last_subscription_verified_at
            else None
        ),
        "offline_grace_hours": OFFLINE_GRACE_HOURS_DEFAULT,
    }


def _sync_tenant_and_firestore(
    db: Session,
    tenant: Tenant,
    sub: Subscription,
    *,
    payment_verified: bool = False,
) -> None:
    eff, allowed, ends = effective_status(sub, tenant)
    tenant.subscription_status = eff if eff != "trial_expired" else "trial_expired"
    if eff == "active":
        tenant.subscription_status = "active"
    elif eff == "trial":
        tenant.subscription_status = "trial"
    elif eff in ("expired", "trial_expired"):
        tenant.subscription_status = eff
    elif eff == "pending_payment":
        tenant.subscription_status = "pending_payment"
    elif eff == "suspended":
        tenant.subscription_status = "suspended"
    tenant.last_subscription_verified_at = datetime.utcnow()
    db.flush()
    sync_subscription_firestore(
        tenant.tenant_uid,
        {
            "subscription_status": tenant.subscription_status,
            "subscription_end": sub.subscription_end.isoformat() + "Z" if sub.subscription_end else None,
            "trial_ends_at": sub.trial_end.isoformat() + "Z" if sub.trial_end else None,
            "billing_status": sub.status,
            "plan": sub.plan,
            "billing_cycle": sub.billing_cycle,
            "payment_verified": payment_verified,
            "access_allowed": allowed,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        },
    )


def create_trial_subscription(db: Session, tenant: Tenant) -> Subscription:
    sub = get_or_create_subscription(db, tenant)
    now = datetime.utcnow()
    sub.status = "trial"
    sub.trial_start = now
    sub.trial_end = tenant.trial_ends_at or (now + timedelta(days=TRIAL_DAYS_DEFAULT))
    sub.plan = sub.plan or "starter"
    tenant.subscription_status = "trial"
    tenant.trial_ends_at = sub.trial_end
    _log(db, tenant.id, "trial_started", f"Trial until {sub.trial_end.isoformat()}")
    _sync_tenant_and_firestore(db, tenant, sub)
    return sub


def start_pending_payment(
    db: Session,
    tenant: Tenant,
    user_email: str,
    plan: str,
    cycle: str,
    *,
    ecocash_phone: Optional[str] = None,
    channel: str = "web",
) -> Tuple[SubscriptionPayment, Dict[str, Any]]:
    plan = plan.lower()
    if plan not in VALID_PLANS:
        raise ValueError("Invalid plan")
    price = get_price(plan, cycle)
    paynow = get_paynow_client()
    if not paynow.is_configured():
        raise RuntimeError("Paynow is not configured on the server")

    sub = get_or_create_subscription(db, tenant)
    reference = f"SUB-{tenant.id}-{uuid.uuid4().hex[:12].upper()}"
    payment = SubscriptionPayment(
        tenant_id=tenant.id,
        payment_reference=reference,
        amount=price.amount_usd,
        currency="USD",
        status="pending",
        payment_method="ecocash" if ecocash_phone else "paynow",
        plan=plan,
        billing_cycle=cycle,
    )
    db.add(payment)
    sub.status = "pending_payment"
    sub.plan = plan
    sub.billing_cycle = cycle
    db.flush()

    pay_email = (user_email or "").strip()
    if not pay_email or "@" not in pay_email:
        raise ValueError(
            "A valid account email is required for Paynow. Update your profile email and try again."
        )

    description = f"DoposAI {price.label}"
    if ecocash_phone:
        try:
            result = paynow.initiate_ecocash(
                reference, pay_email, price.amount_usd, description, ecocash_phone
            )
        except ValueError as e:
            payment.status = "failed"
            _log(db, tenant.id, "payment_init_failed", str(e))
            db.flush()
            raise RuntimeError(str(e)) from e
    else:
        result = paynow.initiate_web(reference, pay_email, price.amount_usd, description)

    if not result.success:
        payment.status = "failed"
        _log(db, tenant.id, "payment_init_failed", result.error or "unknown")
        db.flush()
        raise RuntimeError(result.error or "Could not initiate Paynow payment")

    payment.poll_url = result.poll_url
    _log(db, tenant.id, "payment_initiated", f"{reference} via {channel}")
    _sync_tenant_and_firestore(db, tenant, sub)
    db.flush()

    payload: Dict[str, Any] = {
        "payment_reference": reference,
        "amount": float(price.amount_usd),
        "currency": "USD",
        "plan": plan,
        "billing_cycle": cycle,
        "poll_url": result.poll_url,
        "redirect_url": result.redirect_url,
        "instructions": result.instructions,
        "status": "pending",
    }
    return payment, payload


def _activate_subscription_from_payment(
    db: Session,
    tenant: Tenant,
    sub: Subscription,
    payment: SubscriptionPayment,
) -> None:
    now = datetime.utcnow()
    cycle = payment.billing_cycle or "monthly"
    days = 365 if cycle == "yearly" else 30
    sub.plan = payment.plan or sub.plan
    sub.billing_cycle = cycle
    sub.status = "active"
    sub.subscription_start = now
    sub.subscription_end = now + timedelta(days=days)
    sub.trial_end = sub.trial_end or now
    payment.status = "paid"
    payment.paid_at = now
    tenant.subscription_status = "active"
    _log(
        db,
        tenant.id,
        "subscription_activated",
        f"Plan {sub.plan}/{cycle} until {sub.subscription_end.isoformat()}",
    )
    _sync_tenant_and_firestore(db, tenant, sub, payment_verified=True)
    append_billing_event(
        f"{tenant.tenant_uid}-{payment.payment_reference}",
        {
            "tenant_uid": tenant.tenant_uid,
            "event": "payment_success",
            "reference": payment.payment_reference,
            "amount": float(payment.amount),
            "plan": sub.plan,
            "at": now.isoformat() + "Z",
        },
    )


def verify_and_apply_payment(
    db: Session,
    tenant: Tenant,
    payment_reference: str,
    *,
    poll_url: Optional[str] = None,
) -> Dict[str, Any]:
    payment = (
        db.query(SubscriptionPayment)
        .filter(
            SubscriptionPayment.tenant_id == tenant.id,
            SubscriptionPayment.payment_reference == payment_reference,
        )
        .first()
    )
    if not payment:
        raise ValueError("Payment not found")
    if payment.status == "paid":
        sub = get_or_create_subscription(db, tenant)
        return {"status": "paid", "already_processed": True, **subscription_status_payload(db, tenant)}

    url = poll_url or payment.poll_url
    if not url:
        raise ValueError("No poll URL for this payment")

    paynow = get_paynow_client()
    result = paynow.poll_status(url)
    if not result.paid:
        return {
            "status": payment.status,
            "paynow_status": result.status,
            "paid": False,
            "payment_reference": payment_reference,
        }

    if result.paynow_reference:
        payment.paynow_reference = result.paynow_reference
    sub = get_or_create_subscription(db, tenant)
    _activate_subscription_from_payment(db, tenant, sub, payment)
    db.commit()
    return {
        "status": "paid",
        "paid": True,
        "payment_reference": payment_reference,
        **subscription_status_payload(db, tenant),
    }


def process_paynow_webhook(
    db: Session,
    form: Dict[str, str],
) -> Dict[str, str]:
    """
    Paynow server-to-server result URL (application/x-www-form-urlencoded).
    Idempotent: skips if payment_reference already paid.
    """
    reference = (form.get("reference") or form.get("merchantreference") or "").strip()
    paynow_ref = (form.get("paynowreference") or "").strip()
    poll_url = (form.get("pollurl") or form.get("Pollurl") or "").strip()
    status_raw = (form.get("status") or "").strip().lower()

    if not reference:
        logger.warning("Paynow webhook missing reference: %s", form.keys())
        return {"status": "ignored"}

    payment = (
        db.query(SubscriptionPayment)
        .filter(SubscriptionPayment.payment_reference == reference)
        .first()
    )
    if not payment:
        logger.warning("Paynow webhook unknown reference %s", reference)
        return {"status": "unknown_reference"}

    if payment.status == "paid":
        return {"status": "already_paid"}

    tenant = db.query(Tenant).filter(Tenant.id == payment.tenant_id).first()
    if not tenant:
        return {"status": "no_tenant"}

    if paynow_ref:
        payment.paynow_reference = paynow_ref
    if poll_url:
        payment.poll_url = poll_url

    paid = status_raw in ("paid", "awaiting delivery", "delivered")
    if not paid and poll_url:
        result = get_paynow_client().poll_status(poll_url)
        paid = result.paid
    elif not paid and payment.poll_url:
        result = get_paynow_client().poll_status(payment.poll_url)
        paid = result.paid

    if paid:
        sub = get_or_create_subscription(db, tenant)
        _activate_subscription_from_payment(db, tenant, sub, payment)
        db.commit()
        return {"status": "ok"}
    if status_raw in ("cancelled", "failed"):
        payment.status = "failed"
        _log(db, tenant.id, "payment_failed", f"{reference} status={status_raw}")
        sub = get_or_create_subscription(db, tenant)
        if sub.status == "pending_payment":
            sub.status = "trial" if sub.trial_end and datetime.utcnow() <= sub.trial_end else "expired"
        db.commit()
        return {"status": "failed"}
    return {"status": "pending"}


def upgrade_subscription(
    db: Session,
    tenant: Tenant,
    plan: str,
    cycle: str,
    user_email: str,
    phone: Optional[str],
) -> Dict[str, Any]:
    _, payload = start_pending_payment(
        db,
        tenant,
        user_email,
        plan,
        cycle,
        ecocash_phone=phone,
        channel="upgrade",
    )
    db.commit()
    return payload


def cancel_subscription(db: Session, tenant: Tenant) -> Dict[str, Any]:
    sub = get_or_create_subscription(db, tenant)
    sub.status = "suspended"
    tenant.subscription_status = "suspended"
    _log(db, tenant.id, "subscription_cancelled", "Cancelled by admin")
    _sync_tenant_and_firestore(db, tenant, sub)
    db.commit()
    return subscription_status_payload(db, tenant)


def billing_history(db: Session, tenant_id: int, limit: int = 50) -> Dict[str, Any]:
    payments = (
        db.query(SubscriptionPayment)
        .filter(SubscriptionPayment.tenant_id == tenant_id)
        .order_by(SubscriptionPayment.created_at.desc())
        .limit(limit)
        .all()
    )
    logs = (
        db.query(BillingLog)
        .filter(BillingLog.tenant_id == tenant_id)
        .order_by(BillingLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "payments": [
            {
                "id": p.id,
                "payment_reference": p.payment_reference,
                "paynow_reference": p.paynow_reference,
                "amount": float(p.amount),
                "currency": p.currency,
                "status": p.status,
                "payment_method": p.payment_method,
                "plan": p.plan,
                "billing_cycle": p.billing_cycle,
                "created_at": p.created_at.isoformat() + "Z",
                "paid_at": p.paid_at.isoformat() + "Z" if p.paid_at else None,
            }
            for p in payments
        ],
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "description": e.description,
                "created_at": e.created_at.isoformat() + "Z",
            }
            for e in logs
        ],
    }
