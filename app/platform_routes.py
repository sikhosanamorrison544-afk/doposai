"""Platform-owner APIs: list all SaaS tenants (businesses using the POS)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import auth
from .audit_service import log_audit
from .config import get_platform_owner_emails, get_platform_owner_usernames
from .database import get_db
from .enterprise_models import AuditLog, Branch
from .http_rate_limit import rate_limit_hit as _rate_limit
from .models import StoreSettings, User
from .quotation_models import Tenant
from .saas_models import RefreshToken
from .billing import service as billing_service
from .billing.features import resolve_effective_plan
from .billing.models import BillingLog, ComplimentaryAccessGrant, Subscription, SubscriptionPayment
from .billing.plans import VALID_PLANS
from .billing.service import VALID_COMPLIMENTARY_REASONS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/platform", tags=["platform"])


def is_platform_owner_user(user: User) -> bool:
    """Return True if ``user`` is on the platform-owner allowlist.

    Matches either:
      * email is in ``PLATFORM_OWNER_EMAILS`` (recommended — globally unique), OR
      * username is in ``PLATFORM_OWNER_USERNAMES``.

    Note: username matching is INHERENTLY unsafe in multi-tenant SaaS
    because every tenant's first user defaults to ``admin``. Setting
    ``PLATFORM_OWNER_USERNAMES=admin`` would grant the banner to every
    tenant's primary admin. Use email gating in production.
    """
    if not user.is_active or user.role != "admin":
        return False
    emails = get_platform_owner_emails()
    usernames = get_platform_owner_usernames()
    if not usernames and not emails:
        return False
    user_email = (user.email or "").strip().lower()
    if emails and user_email and user_email in emails:
        return True
    user_username = (user.username or "").strip().lower()
    if usernames and user_username and user_username in usernames:
        return True
    return False


def is_platform_owner_tenant(db: Session, tenant: Tenant) -> bool:
    """True if this business is the platform operator's own tenant (complimentary Pro)."""
    emails = get_platform_owner_emails()
    usernames = get_platform_owner_usernames()
    if not emails and not usernames:
        return False
    tenant_email = (tenant.email or "").strip().lower()
    if emails and tenant_email and tenant_email in emails:
        return True
    admins = (
        db.query(User)
        .filter(
            User.tenant_id == tenant.id,
            User.role == "admin",
            User.is_active == True,  # noqa: E712
        )
        .all()
    )
    return any(is_platform_owner_user(u) for u in admins)


def require_platform_owner(
    user: User = Depends(auth.get_current_active_user),
) -> User:
    emails = get_platform_owner_emails()
    usernames = get_platform_owner_usernames()
    if not usernames and not emails:
        raise HTTPException(
            status_code=403,
            detail=(
                "Platform owner access is not configured. Set "
                "PLATFORM_OWNER_EMAILS (preferred) or PLATFORM_OWNER_USERNAMES "
                "on the server."
            ),
        )
    if not is_platform_owner_user(user):
        raise HTTPException(status_code=403, detail="Platform owner access denied.")
    return user


class PlatformTenantRow(BaseModel):
    id: int
    tenant_uid: str
    business_name: str
    owner_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    subscription_status: str
    billing_status: Optional[str] = None
    plan: Optional[str] = None
    effective_plan: Optional[str] = None
    billing_cycle: Optional[str] = None
    trial_ends_at: Optional[datetime] = None
    subscription_end: Optional[datetime] = None
    access_allowed: bool = True
    entitlement_source: Optional[str] = None
    is_active: bool
    created_at: datetime
    user_count: int
    store_count: int = 0
    admin_usernames: str
    store_display_name: Optional[str] = None


def _platform_audit(
    db: Session,
    *,
    operator: User,
    action: str,
    entity_type: str,
    entity_id: Optional[int],
    old_value: Any = None,
    new_value: Any = None,
    tenant_id: Optional[int] = None,
    request: Optional[Request] = None,
) -> None:
    """Write a privileged platform audit entry (action always ``platform.*``)."""
    log_audit(
        db,
        user=operator,
        action=f"platform.{action}" if not action.startswith("platform.") else action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        tenant_id=tenant_id,
        request=request,
    )


@router.get("/access")
def platform_access_check(current_user: User = Depends(auth.get_current_active_user)):
    """For UI: whether the logged-in user may open the platform tenants page."""
    return {"is_platform_owner": is_platform_owner_user(current_user)}


@router.get("/tenants", response_model=List[PlatformTenantRow])
def list_all_tenants(
    db: Session = Depends(get_db),
    _: User = Depends(require_platform_owner),
):
    tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    rows: List[PlatformTenantRow] = []
    for t in tenants:
        user_count = (
            db.query(func.count(User.id)).filter(User.tenant_id == t.id).scalar() or 0
        )
        admin_names = [
            r[0]
            for r in db.query(User.username)
            .filter(User.tenant_id == t.id, User.role == "admin")
            .order_by(User.id.asc())
            .limit(8)
            .all()
        ]
        ss = (
            db.query(StoreSettings.store_name)
            .filter(StoreSettings.tenant_id == t.id)
            .order_by(StoreSettings.id.asc())
            .first()
        )
        store_display = ss[0] if ss else None
        store_count = (
            db.query(func.count(Branch.id)).filter(Branch.tenant_id == t.id).scalar() or 0
        )
        sub = db.query(Subscription).filter(Subscription.tenant_id == t.id).first()
        entitlement_source = None
        if sub is None:
            grant = billing_service.get_active_complimentary_grant(db, t.id)
            if grant and bool(t.is_active):
                eff_status, access_allowed = "complimentary", True
                eff_plan = (grant.plan or "pro").lower()
                entitlement_source = "complimentary"
            else:
                eff_status = t.subscription_status or "trial"
                access_allowed = bool(t.is_active) and eff_status not in (
                    "suspended",
                    "expired",
                    "trial_expired",
                )
                eff_plan = "pro" if eff_status == "trial" else "starter"
            billing_st = eff_status
            plan_name = None
            cycle = None
            trial_end = t.trial_ends_at
            sub_end = None
        else:
            eff_status, access_allowed, _ = billing_service.effective_status(sub, t, db=db)
            owner_comp = is_platform_owner_tenant(db, t)
            grant = billing_service.get_active_complimentary_grant(db, t.id)
            if owner_comp:
                entitlement_source = "platform_owner"
                eff_plan = resolve_effective_plan(sub, force_pro=True)
            elif grant is not None and eff_status == "complimentary":
                entitlement_source = "complimentary"
                eff_plan = (grant.plan or "starter").lower()
            else:
                entitlement_source = (
                    "trial" if eff_status == "trial" else (
                        "paid" if eff_status == "active" else eff_status
                    )
                )
                eff_plan = resolve_effective_plan(sub, force_pro=False)
            billing_st = sub.status
            plan_name = sub.plan
            cycle = sub.billing_cycle
            trial_end = sub.trial_end or t.trial_ends_at
            sub_end = sub.subscription_end
        rows.append(
            PlatformTenantRow(
                id=t.id,
                tenant_uid=t.tenant_uid,
                business_name=t.name,
                owner_name=t.owner_name,
                phone=t.phone,
                email=t.email,
                subscription_status=eff_status or t.subscription_status or "trial",
                billing_status=billing_st,
                plan=plan_name,
                effective_plan=eff_plan,
                billing_cycle=cycle,
                trial_ends_at=trial_end,
                subscription_end=sub_end,
                access_allowed=access_allowed,
                entitlement_source=entitlement_source,
                is_active=bool(t.is_active),
                created_at=t.created_at,
                user_count=int(user_count),
                store_count=int(store_count),
                admin_usernames=", ".join(admin_names) if admin_names else "—",
                store_display_name=store_display,
            )
        )
    return rows


class AdminResetPasswordBody(BaseModel):
    """Identify the target user by ONE of: user_id, email, or username.

    Why allow three: in practice the platform owner usually has one
    handy from a support ticket (an email), Render logs (a user_id), or
    the platform-tenants page (a username). Sending all three with
    different values raises 400 to avoid accidents.
    """

    user_id: Optional[int] = Field(default=None, ge=1)
    email: Optional[str] = Field(default=None, max_length=320)
    username: Optional[str] = Field(default=None, max_length=64)
    new_password: str = Field(..., min_length=8, max_length=128)


def _validate_password(pw: str) -> None:
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise HTTPException(
            status_code=400,
            detail="Password must contain both letters and numbers.",
        )


def _resolve_user(db: Session, body: AdminResetPasswordBody) -> User:
    selectors = [
        ("user_id", body.user_id),
        ("email", (body.email or "").strip().lower() or None),
        ("username", (body.username or "").strip() or None),
    ]
    provided = [(k, v) for k, v in selectors if v is not None]
    if not provided:
        raise HTTPException(
            status_code=400,
            detail="Provide one of: user_id, email, or username.",
        )

    candidates: List[User] = []
    for key, val in provided:
        q = db.query(User)
        if key == "user_id":
            q = q.filter(User.id == val)
        elif key == "email":
            q = q.filter(func.lower(User.email) == val)
        else:
            q = q.filter(User.username == val)
        u = q.first()
        if u is None:
            raise HTTPException(
                status_code=404,
                detail=f"No user found for {key}={val!r}.",
            )
        candidates.append(u)

    # If the operator gave multiple selectors, they MUST all point at the
    # same row. Refusing the mismatch prevents "I thought I was editing X
    # but I edited Y" support tickets.
    distinct_ids = {u.id for u in candidates}
    if len(distinct_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail=(
                "user_id / email / username refer to different users: "
                + ", ".join(f"{u.username}#{u.id}" for u in candidates)
            ),
        )
    return candidates[0]


@router.post("/reset-user-password")
def admin_reset_user_password(
    request: Request,
    body: AdminResetPasswordBody,
    db: Session = Depends(get_db),
    operator: User = Depends(require_platform_owner),
):
    """Platform-owner override: directly set a user's password.

    Use this when a customer can't receive the /auth/forgot-password
    email (no SMTP yet, dead inbox, etc.). Locked down to accounts
    listed in PLATFORM_OWNER_USERNAMES; no token is generated and no
    email is sent. All existing refresh tokens for the target user are
    revoked so old sessions can't survive the change.
    """
    _rate_limit(request, "admin_reset_pw", max_calls=20, window_sec=600)
    _validate_password(body.new_password)

    target = _resolve_user(db, body)

    if target.id == operator.id:
        # Refuse self-target — they should use /auth/reset-password or the
        # normal change-password flow so the audit trail is consistent.
        raise HTTPException(
            status_code=400,
            detail="Use the normal password-change flow for your own account.",
        )

    target.password_hash = auth.get_password_hash(body.new_password)

    revoked = 0
    for rt in (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == target.id, RefreshToken.revoked_at.is_(None))
        .all()
    ):
        rt.revoked_at = datetime.utcnow()
        revoked += 1

    db.commit()

    logger.warning(
        "PLATFORM-OWNER PASSWORD RESET: operator=%s (id=%s) reset target user_id=%s "
        "username=%s email=%s; revoked %d refresh tokens",
        operator.username,
        operator.id,
        target.id,
        target.username,
        target.email,
        revoked,
    )

    return {
        "ok": True,
        "user_id": target.id,
        "username": target.username,
        "email": target.email,
        "refresh_tokens_revoked": revoked,
    }


class PlatformGrantSubscriptionBody(BaseModel):
    plan: str = Field(..., description="starter, business, or pro")
    billing_cycle: str = Field(default="monthly", description="monthly or yearly")
    duration_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=3650,
        description="For active grants; default 30 (monthly) or 365 (yearly)",
    )
    grant_mode: str = Field(
        default="active",
        description="active = paid access, trial = trial with Pro-level features",
    )
    trial_days: int = Field(default=14, ge=1, le=365)
    note: Optional[str] = Field(default=None, max_length=500)


class PlatformRevokeSubscriptionBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


def _require_tenant(db: Session, tenant_id: int) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Business not found")
    return tenant


@router.post("/tenants/{tenant_id}/subscription/grant")
def platform_grant_tenant_subscription(
    tenant_id: int,
    body: PlatformGrantSubscriptionBody,
    db: Session = Depends(get_db),
    operator: User = Depends(require_platform_owner),
):
    """Manually grant or extend subscription for any tenant (no Paynow)."""
    tenant = _require_tenant(db, tenant_id)
    plan = body.plan.strip().lower()
    if plan not in VALID_PLANS:
        raise HTTPException(
            status_code=400,
            detail=f"plan must be one of: {', '.join(VALID_PLANS)}",
        )
    try:
        payload = billing_service.platform_grant_subscription(
            db,
            tenant,
            plan=plan,
            billing_cycle=body.billing_cycle,
            duration_days=body.duration_days,
            grant_mode=body.grant_mode,
            trial_days=body.trial_days,
            operator_username=operator.username,
            note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.warning(
        "PLATFORM GRANT: operator=%s tenant_id=%s plan=%s mode=%s",
        operator.username,
        tenant_id,
        plan,
        body.grant_mode,
    )
    return {"ok": True, "subscription": payload}


@router.post("/tenants/{tenant_id}/subscription/revoke")
def platform_revoke_tenant_subscription(
    tenant_id: int,
    body: PlatformRevokeSubscriptionBody = PlatformRevokeSubscriptionBody(),
    db: Session = Depends(get_db),
    operator: User = Depends(require_platform_owner),
):
    """Suspend tenant subscription (revoke access until re-granted)."""
    tenant = _require_tenant(db, tenant_id)
    payload = billing_service.platform_revoke_subscription(
        db,
        tenant,
        operator_username=operator.username,
        reason=body.reason,
    )
    logger.warning(
        "PLATFORM REVOKE: operator=%s tenant_id=%s reason=%s",
        operator.username,
        tenant_id,
        body.reason or "",
    )
    _platform_audit(
        db,
        operator=operator,
        action="subscription.revoke",
        entity_type="tenant",
        entity_id=tenant.id,
        old_value={"status": "active"},
        new_value={"status": "suspended", "reason": body.reason},
        tenant_id=tenant.id,
        request=None,
    )
    db.commit()
    return {"ok": True, "subscription": payload}


# ── Overview / dashboard ─────────────────────────────────────────────────────


@router.get("/overview")
def platform_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_platform_owner),
):
    now = datetime.utcnow()
    total_businesses = db.query(func.count(Tenant.id)).scalar() or 0
    active_accounts = (
        db.query(func.count(Tenant.id)).filter(Tenant.is_active.is_(True)).scalar() or 0
    )
    suspended_accounts = (
        db.query(func.count(Tenant.id)).filter(Tenant.is_active.is_(False)).scalar() or 0
    )
    total_users = db.query(func.count(User.id)).scalar() or 0
    total_stores = db.query(func.count(Branch.id)).scalar() or 0

    subs = db.query(Subscription).all()
    trial = paid = expired = suspended_sub = pending = 0
    for s in subs:
        t = db.query(Tenant).filter(Tenant.id == s.tenant_id).first()
        if not t:
            continue
        st, _, _ = billing_service.effective_status(s, t, db=db)
        if st == "trial":
            trial += 1
        elif st == "active":
            paid += 1
        elif st == "complimentary":
            pass  # counted via grants below
        elif st in ("expired", "trial_expired"):
            expired += 1
        elif st == "suspended":
            suspended_sub += 1
        elif st == "pending_payment":
            pending += 1

    complimentary_active = 0
    grants = (
        db.query(ComplimentaryAccessGrant)
        .filter(ComplimentaryAccessGrant.revoked_at.is_(None))
        .all()
    )
    for g in grants:
        if g.starts_at <= now and (g.ends_at is None or g.ends_at > now):
            complimentary_active += 1

    recent_regs = (
        db.query(Tenant).order_by(Tenant.created_at.desc()).limit(10).all()
    )
    recent_billing = (
        db.query(BillingLog)
        .order_by(BillingLog.created_at.desc())
        .limit(15)
        .all()
    )
    tenant_names = {
        t.id: t.name
        for t in db.query(Tenant)
        .filter(Tenant.id.in_({e.tenant_id for e in recent_billing} or {-1}))
        .all()
    }

    return {
        "totals": {
            "businesses": int(total_businesses),
            "users": int(total_users),
            "stores": int(total_stores),
            "active_accounts": int(active_accounts),
            "suspended_accounts": int(suspended_accounts),
            "trial_accounts": trial,
            "paid_subscriptions": paid,
            "complimentary_accounts": complimentary_active,
            "expired_subscriptions": expired,
            "suspended_subscriptions": suspended_sub,
            "pending_payment": pending,
        },
        "recent_registrations": [
            {
                "id": t.id,
                "tenant_uid": t.tenant_uid,
                "business_name": t.name,
                "owner_name": t.owner_name,
                "email": t.email,
                "subscription_status": t.subscription_status,
                "is_active": bool(t.is_active),
                "created_at": t.created_at.isoformat() + "Z" if t.created_at else None,
            }
            for t in recent_regs
        ],
        "recent_subscription_changes": [
            {
                "id": e.id,
                "tenant_id": e.tenant_id,
                "business_name": tenant_names.get(e.tenant_id),
                "event_type": e.event_type,
                "description": e.description,
                "created_at": e.created_at.isoformat() + "Z" if e.created_at else None,
            }
            for e in recent_billing
        ],
    }


# ── Tenant detail / activate / suspend ───────────────────────────────────────


class TenantStatusBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


@router.get("/tenants/{tenant_id}")
def platform_tenant_detail(
    tenant_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_platform_owner),
):
    tenant = _require_tenant(db, tenant_id)
    users = (
        db.query(User)
        .filter(User.tenant_id == tenant.id)
        .order_by(User.id.asc())
        .all()
    )
    branches = (
        db.query(Branch)
        .filter(Branch.tenant_id == tenant.id)
        .order_by(Branch.id.asc())
        .all()
    )
    sub_payload = billing_service.subscription_status_payload(db, tenant)
    grants = (
        db.query(ComplimentaryAccessGrant)
        .filter(ComplimentaryAccessGrant.tenant_id == tenant.id)
        .order_by(ComplimentaryAccessGrant.id.desc())
        .limit(50)
        .all()
    )
    history = (
        db.query(BillingLog)
        .filter(BillingLog.tenant_id == tenant.id)
        .order_by(BillingLog.created_at.desc())
        .limit(40)
        .all()
    )
    payments = (
        db.query(SubscriptionPayment)
        .filter(SubscriptionPayment.tenant_id == tenant.id)
        .order_by(SubscriptionPayment.created_at.desc())
        .limit(20)
        .all()
    )
    manager_ids = {b.manager_user_id for b in branches if b.manager_user_id}
    managers = {
        u.id: u
        for u in db.query(User).filter(User.id.in_(manager_ids or {-1})).all()
    }
    return {
        "tenant": {
            "id": tenant.id,
            "tenant_uid": tenant.tenant_uid,
            "business_name": tenant.name,
            "owner_name": tenant.owner_name,
            "phone": tenant.phone,
            "email": tenant.email,
            "is_active": bool(tenant.is_active),
            "subscription_status": tenant.subscription_status,
            "created_at": tenant.created_at.isoformat() + "Z" if tenant.created_at else None,
        },
        "subscription": sub_payload,
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.full_name,
                "email": u.email,
                "role": u.role,
                "is_active": bool(u.is_active),
                "created_at": u.created_at.isoformat() + "Z" if u.created_at else None,
            }
            for u in users
        ],
        "stores": [
            {
                "id": b.id,
                "name": b.name,
                "code": b.code,
                "address": b.address,
                "is_active": bool(b.is_active),
                "is_default": bool(b.is_default),
                "manager_user_id": b.manager_user_id,
                "manager_username": (
                    managers[b.manager_user_id].username
                    if b.manager_user_id in managers
                    else None
                ),
                "created_at": b.created_at.isoformat() + "Z" if b.created_at else None,
            }
            for b in branches
        ],
        "complimentary_grants": [
            billing_service.complimentary_grant_to_dict(g) for g in grants
        ],
        "billing_history": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "description": e.description,
                "created_at": e.created_at.isoformat() + "Z" if e.created_at else None,
            }
            for e in history
        ],
        "payments": [
            {
                "id": p.id,
                "payment_reference": p.payment_reference,
                "amount": float(p.amount) if p.amount is not None else None,
                "currency": p.currency,
                "status": p.status,
                "plan": p.plan,
                "billing_cycle": p.billing_cycle,
                "created_at": p.created_at.isoformat() + "Z" if p.created_at else None,
                "paid_at": p.paid_at.isoformat() + "Z" if p.paid_at else None,
            }
            for p in payments
        ],
    }


@router.post("/tenants/{tenant_id}/activate")
def platform_activate_tenant(
    tenant_id: int,
    request: Request,
    body: TenantStatusBody = TenantStatusBody(),
    db: Session = Depends(get_db),
    operator: User = Depends(require_platform_owner),
):
    tenant = _require_tenant(db, tenant_id)
    old = {"is_active": bool(tenant.is_active)}
    tenant.is_active = True
    _platform_audit(
        db,
        operator=operator,
        action="tenant.activate",
        entity_type="tenant",
        entity_id=tenant.id,
        old_value=old,
        new_value={"is_active": True, "reason": body.reason},
        tenant_id=tenant.id,
        request=request,
    )
    sub = billing_service.get_or_create_subscription(db, tenant)
    billing_service._sync_tenant_and_firestore(db, tenant, sub, payment_verified=False)
    db.commit()
    return {"ok": True, "tenant_id": tenant.id, "is_active": True}


@router.post("/tenants/{tenant_id}/suspend")
def platform_suspend_tenant(
    tenant_id: int,
    request: Request,
    body: TenantStatusBody = TenantStatusBody(),
    db: Session = Depends(get_db),
    operator: User = Depends(require_platform_owner),
):
    tenant = _require_tenant(db, tenant_id)
    old = {"is_active": bool(tenant.is_active)}
    tenant.is_active = False
    _platform_audit(
        db,
        operator=operator,
        action="tenant.suspend",
        entity_type="tenant",
        entity_id=tenant.id,
        old_value=old,
        new_value={"is_active": False, "reason": body.reason},
        tenant_id=tenant.id,
        request=request,
    )
    sub = billing_service.get_or_create_subscription(db, tenant)
    billing_service._sync_tenant_and_firestore(db, tenant, sub, payment_verified=False)
    db.commit()
    return {"ok": True, "tenant_id": tenant.id, "is_active": False}


# ── Platform-wide users ──────────────────────────────────────────────────────


@router.get("/users")
def platform_list_users(
    q: Optional[str] = Query(default=None, max_length=120),
    tenant_id: Optional[int] = None,
    status: Optional[str] = Query(default=None, description="active|inactive"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_platform_owner),
):
    query = db.query(User)
    if tenant_id is not None:
        query = query.filter(User.tenant_id == tenant_id)
    if status == "active":
        query = query.filter(User.is_active.is_(True))
    elif status == "inactive":
        query = query.filter(User.is_active.is_(False))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                User.username.ilike(like),
                User.email.ilike(like),
                User.full_name.ilike(like),
            )
        )
    total = query.count()
    rows = (
        query.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    tenant_ids = {u.tenant_id for u in rows if u.tenant_id}
    tenants = {
        t.id: t
        for t in db.query(Tenant).filter(Tenant.id.in_(tenant_ids or {-1})).all()
    }
    # Best-effort last login from newest non-revoked refresh token created_at.
    last_login_map: Dict[int, Optional[datetime]] = {}
    if rows:
        user_ids = [u.id for u in rows]
        for uid in user_ids:
            rt = (
                db.query(RefreshToken)
                .filter(RefreshToken.user_id == uid)
                .order_by(RefreshToken.created_at.desc())
                .first()
            )
            last_login_map[uid] = rt.created_at if rt else None

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.full_name,
                "email": u.email,
                "role": u.role,
                "is_active": bool(u.is_active),
                "tenant_id": u.tenant_id,
                "business_name": tenants[u.tenant_id].name if u.tenant_id in tenants else None,
                "created_at": u.created_at.isoformat() + "Z" if u.created_at else None,
                "last_login": (
                    last_login_map[u.id].isoformat() + "Z"
                    if last_login_map.get(u.id)
                    else None
                ),
            }
            for u in rows
        ],
    }


class UserStatusBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("/users/{user_id}/activate")
def platform_activate_user(
    user_id: int,
    request: Request,
    body: UserStatusBody = UserStatusBody(),
    db: Session = Depends(get_db),
    operator: User = Depends(require_platform_owner),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    old = {"is_active": bool(target.is_active)}
    target.is_active = True
    _platform_audit(
        db,
        operator=operator,
        action="user.activate",
        entity_type="user",
        entity_id=target.id,
        old_value=old,
        new_value={"is_active": True, "reason": body.reason},
        tenant_id=target.tenant_id,
        request=request,
    )
    db.commit()
    return {"ok": True, "user_id": target.id, "is_active": True}


@router.post("/users/{user_id}/suspend")
def platform_suspend_user(
    user_id: int,
    request: Request,
    body: UserStatusBody = UserStatusBody(),
    db: Session = Depends(get_db),
    operator: User = Depends(require_platform_owner),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == operator.id:
        raise HTTPException(status_code=400, detail="Cannot suspend your own platform account.")
    old = {"is_active": bool(target.is_active)}
    target.is_active = False
    for rt in (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == target.id, RefreshToken.revoked_at.is_(None))
        .all()
    ):
        rt.revoked_at = datetime.utcnow()
    _platform_audit(
        db,
        operator=operator,
        action="user.suspend",
        entity_type="user",
        entity_id=target.id,
        old_value=old,
        new_value={"is_active": False, "reason": body.reason},
        tenant_id=target.tenant_id,
        request=request,
    )
    db.commit()
    return {"ok": True, "user_id": target.id, "is_active": False}


# ── Stores / branches ────────────────────────────────────────────────────────


@router.get("/branches")
def platform_list_branches(
    q: Optional[str] = Query(default=None, max_length=120),
    tenant_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_platform_owner),
):
    query = db.query(Branch)
    if tenant_id is not None:
        query = query.filter(Branch.tenant_id == tenant_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(Branch.name.ilike(like), Branch.code.ilike(like), Branch.address.ilike(like))
        )
    total = query.count()
    rows = (
        query.order_by(Branch.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    tenant_ids = {b.tenant_id for b in rows if b.tenant_id}
    tenants = {
        t.id: t
        for t in db.query(Tenant).filter(Tenant.id.in_(tenant_ids or {-1})).all()
    }
    manager_ids = {b.manager_user_id for b in rows if b.manager_user_id}
    managers = {
        u.id: u
        for u in db.query(User).filter(User.id.in_(manager_ids or {-1})).all()
    }
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": b.id,
                "name": b.name,
                "code": b.code,
                "address": b.address,
                "phone": b.phone,
                "is_active": bool(b.is_active),
                "is_default": bool(b.is_default),
                "tenant_id": b.tenant_id,
                "business_name": tenants[b.tenant_id].name if b.tenant_id in tenants else None,
                "manager_user_id": b.manager_user_id,
                "manager_username": (
                    managers[b.manager_user_id].username
                    if b.manager_user_id in managers
                    else None
                ),
                "created_at": b.created_at.isoformat() + "Z" if b.created_at else None,
            }
            for b in rows
        ],
    }


# ── Complimentary access grants ──────────────────────────────────────────────


class ComplimentaryGrantBody(BaseModel):
    tenant_id: int = Field(..., ge=1)
    plan: str = Field(default="pro")
    reason: str = Field(..., description="promotional|demo|testing|partnership|special|support")
    note: Optional[str] = Field(default=None, max_length=1000)
    permanent: bool = False
    duration_days: Optional[int] = Field(default=None, ge=1, le=3650)
    ends_at: Optional[datetime] = None


class ComplimentaryExtendBody(BaseModel):
    permanent: bool = False
    duration_days: Optional[int] = Field(default=None, ge=1, le=3650)
    ends_at: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=1000)


class ComplimentaryRevokeBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


@router.get("/complimentary-grants")
def platform_list_complimentary_grants(
    tenant_id: Optional[int] = None,
    active_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_platform_owner),
):
    query = db.query(ComplimentaryAccessGrant)
    if tenant_id is not None:
        query = query.filter(ComplimentaryAccessGrant.tenant_id == tenant_id)
    if active_only:
        now = datetime.utcnow()
        query = query.filter(
            ComplimentaryAccessGrant.revoked_at.is_(None),
            ComplimentaryAccessGrant.starts_at <= now,
            or_(
                ComplimentaryAccessGrant.ends_at.is_(None),
                ComplimentaryAccessGrant.ends_at > now,
            ),
        )
    total = query.count()
    rows = (
        query.order_by(ComplimentaryAccessGrant.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    tenant_ids = {g.tenant_id for g in rows}
    tenants = {
        t.id: t
        for t in db.query(Tenant).filter(Tenant.id.in_(tenant_ids or {-1})).all()
    }
    items = []
    for g in rows:
        d = billing_service.complimentary_grant_to_dict(g)
        t = tenants.get(g.tenant_id)
        d["business_name"] = t.name if t else None
        items.append(d)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "reasons": sorted(VALID_COMPLIMENTARY_REASONS),
        "items": items,
    }


@router.post("/complimentary-grants")
def platform_create_complimentary_grant(
    request: Request,
    body: ComplimentaryGrantBody,
    db: Session = Depends(get_db),
    operator: User = Depends(require_platform_owner),
):
    tenant = _require_tenant(db, body.tenant_id)
    ends_at = body.ends_at
    if not body.permanent and ends_at is None and body.duration_days:
        ends_at = datetime.utcnow() + timedelta(days=int(body.duration_days))
    try:
        grant = billing_service.grant_complimentary_access(
            db,
            tenant,
            plan=body.plan,
            reason=body.reason,
            note=body.note,
            ends_at=ends_at,
            permanent=body.permanent,
            operator_user_id=operator.id,
            operator_username=operator.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Confirm no payment was created for this grant.
    payment_count = (
        db.query(func.count(SubscriptionPayment.id))
        .filter(
            SubscriptionPayment.tenant_id == tenant.id,
            SubscriptionPayment.created_at >= grant.created_at - timedelta(seconds=2),
        )
        .scalar()
        or 0
    )
    _platform_audit(
        db,
        operator=operator,
        action="complimentary.grant",
        entity_type="complimentary_access_grant",
        entity_id=grant.id,
        old_value=None,
        new_value=billing_service.complimentary_grant_to_dict(grant),
        tenant_id=tenant.id,
        request=request,
    )
    db.commit()
    logger.warning(
        "PLATFORM COMPLIMENTARY GRANT: operator=%s tenant_id=%s grant_id=%s plan=%s",
        operator.username,
        tenant.id,
        grant.id,
        grant.plan,
    )
    return {
        "ok": True,
        "grant": billing_service.complimentary_grant_to_dict(grant),
        "subscription": billing_service.subscription_status_payload(db, tenant),
        "payment_created": bool(payment_count),
    }


@router.post("/complimentary-grants/{grant_id}/extend")
def platform_extend_complimentary_grant(
    grant_id: int,
    request: Request,
    body: ComplimentaryExtendBody,
    db: Session = Depends(get_db),
    operator: User = Depends(require_platform_owner),
):
    grant = (
        db.query(ComplimentaryAccessGrant)
        .filter(ComplimentaryAccessGrant.id == grant_id)
        .first()
    )
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")
    ends_at = body.ends_at
    if not body.permanent and ends_at is None and body.duration_days:
        base = grant.ends_at if grant.ends_at and grant.ends_at > datetime.utcnow() else datetime.utcnow()
        ends_at = base + timedelta(days=int(body.duration_days))
    old = billing_service.complimentary_grant_to_dict(grant)
    try:
        grant = billing_service.extend_complimentary_grant(
            db,
            grant,
            ends_at=ends_at,
            permanent=body.permanent,
            note=body.note,
            operator_user_id=operator.id,
            operator_username=operator.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _platform_audit(
        db,
        operator=operator,
        action="complimentary.extend",
        entity_type="complimentary_access_grant",
        entity_id=grant.id,
        old_value=old,
        new_value=billing_service.complimentary_grant_to_dict(grant),
        tenant_id=grant.tenant_id,
        request=request,
    )
    db.commit()
    return {"ok": True, "grant": billing_service.complimentary_grant_to_dict(grant)}


@router.post("/complimentary-grants/{grant_id}/revoke")
def platform_revoke_complimentary_grant(
    grant_id: int,
    request: Request,
    body: ComplimentaryRevokeBody = ComplimentaryRevokeBody(),
    db: Session = Depends(get_db),
    operator: User = Depends(require_platform_owner),
):
    grant = (
        db.query(ComplimentaryAccessGrant)
        .filter(ComplimentaryAccessGrant.id == grant_id)
        .first()
    )
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")
    old = billing_service.complimentary_grant_to_dict(grant)
    grant = billing_service.revoke_complimentary_grant(
        db,
        grant,
        reason=body.reason,
        operator_user_id=operator.id,
        operator_username=operator.username,
    )
    _platform_audit(
        db,
        operator=operator,
        action="complimentary.revoke",
        entity_type="complimentary_access_grant",
        entity_id=grant.id,
        old_value=old,
        new_value=billing_service.complimentary_grant_to_dict(grant),
        tenant_id=grant.tenant_id,
        request=request,
    )
    db.commit()
    tenant = db.query(Tenant).filter(Tenant.id == grant.tenant_id).first()
    return {
        "ok": True,
        "grant": billing_service.complimentary_grant_to_dict(grant),
        "subscription": (
            billing_service.subscription_status_payload(db, tenant) if tenant else None
        ),
    }


# ── Payments (read-only cross-tenant) ────────────────────────────────────────


@router.get("/payments")
def platform_list_payments(
    tenant_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_platform_owner),
):
    query = db.query(SubscriptionPayment)
    if tenant_id is not None:
        query = query.filter(SubscriptionPayment.tenant_id == tenant_id)
    if status:
        query = query.filter(SubscriptionPayment.status == status.strip().lower())
    total = query.count()
    rows = (
        query.order_by(SubscriptionPayment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    tenant_ids = {p.tenant_id for p in rows}
    tenants = {
        t.id: t
        for t in db.query(Tenant).filter(Tenant.id.in_(tenant_ids or {-1})).all()
    }
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": p.id,
                "tenant_id": p.tenant_id,
                "business_name": tenants[p.tenant_id].name if p.tenant_id in tenants else None,
                "payment_reference": p.payment_reference,
                "paynow_reference": p.paynow_reference,
                "amount": float(p.amount) if p.amount is not None else None,
                "currency": p.currency,
                "status": p.status,
                "payment_method": p.payment_method,
                "plan": p.plan,
                "billing_cycle": p.billing_cycle,
                "created_at": p.created_at.isoformat() + "Z" if p.created_at else None,
                "paid_at": p.paid_at.isoformat() + "Z" if p.paid_at else None,
            }
            for p in rows
        ],
    }


# ── Audit logs (platform privileged) ─────────────────────────────────────────


@router.get("/audit-logs")
def platform_audit_logs(
    action: Optional[str] = None,
    tenant_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_platform_owner),
):
    query = db.query(AuditLog).filter(AuditLog.action.like("platform.%"))
    if action:
        query = query.filter(AuditLog.action == action)
    if tenant_id is not None:
        query = query.filter(AuditLog.tenant_id == tenant_id)
    total = query.count()
    rows = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "username": r.username,
                "user_id": r.user_id,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "tenant_id": r.tenant_id,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "ip_address": r.ip_address,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/settings")
def platform_settings(
    _: User = Depends(require_platform_owner),
):
    emails = sorted(get_platform_owner_emails())
    usernames = sorted(get_platform_owner_usernames())
    return {
        "platform_owner_emails_configured": len(emails) > 0,
        "platform_owner_usernames_configured": len(usernames) > 0,
        "platform_owner_email_count": len(emails),
        "platform_owner_username_count": len(usernames),
        "complimentary_reasons": sorted(VALID_COMPLIMENTARY_REASONS),
        "plans": list(VALID_PLANS),
        "note": (
            "Platform owner identity is controlled by PLATFORM_OWNER_EMAILS / "
            "PLATFORM_OWNER_USERNAMES environment variables. Ordinary store "
            "admins cannot grant complimentary access."
        ),
    }
