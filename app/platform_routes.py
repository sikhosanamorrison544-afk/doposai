"""Platform-owner APIs: list all SaaS tenants (businesses using the POS)."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth
from .config import PLATFORM_OWNER_EMAILS, PLATFORM_OWNER_USERNAMES
from .database import get_db
from .http_rate_limit import rate_limit_hit as _rate_limit
from .models import StoreSettings, User
from .quotation_models import Tenant
from .saas_models import RefreshToken
from .billing import service as billing_service
from .billing.features import resolve_effective_plan
from .billing.models import Subscription
from .billing.plans import VALID_PLANS

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
    if not PLATFORM_OWNER_USERNAMES and not PLATFORM_OWNER_EMAILS:
        return False
    user_email = (user.email or "").strip().lower()
    if PLATFORM_OWNER_EMAILS and user_email and user_email in PLATFORM_OWNER_EMAILS:
        return True
    user_username = (user.username or "").strip().lower()
    if (
        PLATFORM_OWNER_USERNAMES
        and user_username
        and user_username in PLATFORM_OWNER_USERNAMES
    ):
        return True
    return False


def is_platform_owner_tenant(db: Session, tenant: Tenant) -> bool:
    """True if this business is the platform operator's own tenant (complimentary Pro)."""
    if not PLATFORM_OWNER_EMAILS and not PLATFORM_OWNER_USERNAMES:
        return False
    tenant_email = (tenant.email or "").strip().lower()
    if PLATFORM_OWNER_EMAILS and tenant_email and tenant_email in PLATFORM_OWNER_EMAILS:
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
    if not PLATFORM_OWNER_USERNAMES and not PLATFORM_OWNER_EMAILS:
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
    is_active: bool
    created_at: datetime
    user_count: int
    admin_usernames: str
    store_display_name: Optional[str] = None


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
        sub = db.query(Subscription).filter(Subscription.tenant_id == t.id).first()
        if sub is None:
            eff_status = t.subscription_status or "trial"
            access_allowed = eff_status not in ("suspended", "expired", "trial_expired")
            eff_plan = "pro" if eff_status == "trial" else "starter"
            billing_st = eff_status
            plan_name = None
            cycle = None
            trial_end = t.trial_ends_at
            sub_end = None
        else:
            eff_status, access_allowed, _ = billing_service.effective_status(sub, t, db=db)
            complimentary = is_platform_owner_tenant(db, t)
            eff_plan = resolve_effective_plan(sub, force_pro=complimentary)
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
                subscription_status=t.subscription_status or eff_status or "trial",
                billing_status=billing_st,
                plan=plan_name,
                effective_plan=eff_plan,
                billing_cycle=cycle,
                trial_ends_at=trial_end,
                subscription_end=sub_end,
                access_allowed=access_allowed,
                is_active=bool(t.is_active),
                created_at=t.created_at,
                user_count=int(user_count),
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
    return {"ok": True, "subscription": payload}
