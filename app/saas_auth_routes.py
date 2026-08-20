"""SaaS authentication: register, login, refresh, logout, verify, forgot/reset password."""
from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from jose import JWTError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth
from .config import PLATFORM_BRAND_NAME, PLATFORM_MOTTO, WEB_PUBLIC_URL
from .database import SessionLocal, get_db
from .deferred_tasks import run_in_background
from .billing import service as billing_service
from .email_service import EmailService
from .firestore_service import fetch_tenant_subscription, upsert_tenant_security_record
from .models import StoreSettings, User
from .quotation_models import Tenant
from .saas_models import PasswordResetToken, RefreshToken

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

from .http_rate_limit import rate_limit_hit as _rate_limit


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:40] or "business"


def _mask_email(email: str) -> str:
    """Mask an email for display on the reset page (never trust the client)."""
    email = (email or "").strip()
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def _store_settings_for_token_user(db: Session, user: User) -> Optional[StoreSettings]:
    """Tenant-scoped StoreSettings for the exact reset-token user only.

    Never uses ``StoreSettings`` without a tenant predicate, never ``.first()``
    across all stores, and never authenticated-session helpers.
    """
    tid = user.tenant_id
    if tid is None:
        settings = (
            db.query(StoreSettings)
            .filter(StoreSettings.tenant_id.is_(None))
            .order_by(StoreSettings.id.asc())
            .first()
        )
    else:
        settings = (
            db.query(StoreSettings)
            .filter(StoreSettings.tenant_id == int(tid))
            .order_by(StoreSettings.id.asc())
            .first()
        )
    if settings is None:
        return None
    # Belt-and-suspenders: reject any row that does not match the token user.
    if tid is None:
        if settings.tenant_id is not None:
            return None
    elif settings.tenant_id != int(tid):
        return None
    return settings


def _store_name_for_user(db: Session, user: User) -> str:
    """Resolve store display name only from the token's user → tenant settings.

    Chain: token user → tenant_id → tenant-scoped StoreSettings.store_name.
    Missing settings fall back to that tenant's ``Tenant.name``, then the neutral
    platform brand. Never ``STORE_NAME`` env, never another tenant's row.
    """
    settings = _store_settings_for_token_user(db, user)
    if settings and (settings.store_name or "").strip():
        return settings.store_name.strip()
    if user.tenant_id is not None:
        tenant = db.query(Tenant).filter(Tenant.id == int(user.tenant_id)).first()
        if tenant and (tenant.name or "").strip():
            return tenant.name.strip()
    return (PLATFORM_BRAND_NAME or "Store").strip() or "Store"


def _auth_no_store_json(payload: Dict[str, Any], status_code: int = 200) -> JSONResponse:
    """JSON response that must never be cached (password-reset identity)."""
    resp = JSONResponse(content=payload, status_code=status_code)
    resp.headers["Cache-Control"] = "no-store, private"
    resp.headers["Pragma"] = "no-cache"
    return resp


def _active_users_by_email(db: Session, email: str) -> List[User]:
    """All active users with this email (emails are app-unique; DB may still allow dupes)."""
    if not email:
        return []
    return (
        db.query(User)
        .filter(
            User.email.isnot(None),
            func.lower(User.email) == email.strip().lower(),
            User.is_active.is_(True),
        )
        .order_by(User.id.asc())
        .all()
    )


def _invalidate_unused_reset_tokens(
    db: Session, user_id: int, *, except_id: Optional[int] = None
) -> None:
    now = datetime.utcnow()
    q = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user_id,
        PasswordResetToken.used_at.is_(None),
    )
    if except_id is not None:
        q = q.filter(PasswordResetToken.id != except_id)
    for row in q.all():
        row.used_at = now


def _lookup_reset_token(
    db: Session, raw_token: str
) -> Tuple[Optional[PasswordResetToken], Optional[User]]:
    """Resolve token_hash → reset row → active user. No client IDs consulted."""
    raw = (raw_token or "").strip()
    if len(raw) < 10:
        return None, None
    h = auth.hash_token(raw)
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == h)
        .first()
    )
    if not row:
        return None, None
    if row.used_at is not None:
        return None, None
    if row.expires_at < datetime.utcnow():
        return None, None
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user or not user.is_active:
        return None, None
    return row, user


def _issue_reset_token_for_user(db: Session, user: User) -> str:
    """Create a hashed reset token for one exact user; invalidate prior unused tokens."""
    _invalidate_unused_reset_tokens(db, user.id)
    raw = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=auth.hash_token(raw),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
    )
    db.flush()
    return raw


class RegisterBody(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=120)
    owner_name: str = Field(..., min_length=2, max_length=120)
    phone: str = Field(..., min_length=6, max_length=32)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("Password must contain letters and numbers")
        return v


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class RefreshBody(BaseModel):
    refresh_token: str


class LogoutBody(BaseModel):
    refresh_token: Optional[str] = None


class ForgotPasswordBody(BaseModel):
    email: EmailStr


class ResetPasswordBody(BaseModel):
    """Client may only send token + passwords. Extra IDs/emails are ignored."""

    model_config = ConfigDict(extra="ignore")

    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: Optional[str] = None

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("Password must contain letters and numbers")
        return v


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: int
    tenant_id: Optional[int] = None
    tenant_uid: Optional[str] = None
    username: str
    role: str
    subscription_status: str
    trial_ends_at: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None
    landing_path: str = "/"


class VerifyResponse(BaseModel):
    valid: bool
    user_id: Optional[int] = None
    tenant_id: Optional[int] = None
    tenant_uid: Optional[str] = None
    subscription_status: Optional[str] = None
    trial_ends_at: Optional[datetime] = None
    role: Optional[str] = None
    username: Optional[str] = None
    last_verified_at: Optional[datetime] = None


def _subscription_effective(db: Session, tenant: Optional[Tenant]) -> str:
    if not tenant:
        return "active"
    try:
        sub = billing_service.get_or_create_subscription(db, tenant)
        eff, _, _ = billing_service.effective_status(sub, tenant)
        return eff
    except Exception:
        if tenant.subscription_status == "trial" and tenant.trial_ends_at:
            if datetime.utcnow() > tenant.trial_ends_at:
                return "trial_expired"
        return tenant.subscription_status or "trial"


def _register_cloud_sync(
    tenant_id: int, tenant_uid: str, security_payload: Dict[str, Any]
) -> None:
    """Firestore + billing plane sync after registration (runs off the HTTP thread)."""
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return
        fs_id = upsert_tenant_security_record(tenant_uid, security_payload)
        if fs_id:
            tenant.firestore_doc_id = fs_id
        billing_service.sync_tenant_firestore_after_register(db, tenant_id)
    except Exception as e:
        logger.warning(
            "Register cloud sync failed for tenant %s: %s", tenant_uid, e, exc_info=True
        )
        db.rollback()
    finally:
        db.close()


def _issue_tokens(db: Session, user: User, tenant: Optional[Tenant]) -> AuthResponse:
    tid = user.tenant_id
    tenant_uid = tenant.tenant_uid if tenant else None
    sub_status = _subscription_effective(db, tenant)
    payload: Dict[str, Any] = {"sub": user.username, "role": user.role}
    if tid is not None:
        payload["tid"] = tid
    access = auth.create_access_token(data=payload)
    raw_refresh = auth.new_opaque_refresh_token()
    rhash = auth.hash_token(raw_refresh)
    exp = datetime.utcnow() + timedelta(days=auth.REFRESH_TOKEN_EXPIRE_DAYS)
    db.add(RefreshToken(user_id=user.id, token_hash=rhash, expires_at=exp))
    if tenant:
        tenant.last_subscription_verified_at = datetime.utcnow()
    db.commit()
    from .landing import post_login_path

    return AuthResponse(
        access_token=access,
        refresh_token=raw_refresh,
        expires_in=auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=user.id,
        tenant_id=tid,
        tenant_uid=tenant_uid,
        username=user.username,
        role=user.role,
        subscription_status=sub_status,
        trial_ends_at=tenant.trial_ends_at if tenant else None,
        last_verified_at=tenant.last_subscription_verified_at if tenant else None,
        landing_path=post_login_path(user),
    )


def _auth_response_with_cookie(body: AuthResponse) -> JSONResponse:
    """Same JWT cookie as ``/api/auth/token`` for HTML route guards."""
    response = JSONResponse(content=body.model_dump(mode="json"))
    auth.attach_access_cookie(response, body.access_token)
    return response


@router.post("/register")
def auth_register(request: Request, body: RegisterBody, db: Session = Depends(get_db)):
    _rate_limit(request, "register", max_calls=10, window_sec=300)
    email_norm = body.email.strip().lower()
    existing = (
        db.query(User)
        .filter(User.email.isnot(None), func.lower(User.email) == email_norm)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    base_username = email_norm.split("@")[0] + "-" + _slug(body.business_name)[:20]
    username = base_username
    n = 0
    while db.query(User).filter(User.username == username).first():
        n += 1
        username = f"{base_username}-{n}"

    tenant_uid = str(uuid.uuid4())
    trial_end = datetime.utcnow() + timedelta(days=14)
    tenant = Tenant(
        tenant_uid=tenant_uid,
        name=body.business_name.strip(),
        owner_name=body.owner_name.strip(),
        phone=body.phone.strip(),
        email=email_norm,
        is_active=True,
        subscription_status="trial",
        trial_ends_at=trial_end,
        firestore_doc_id=None,
    )
    db.add(tenant)
    db.flush()

    user = User(
        username=username,
        full_name=body.owner_name.strip(),
        email=email_norm,
        password_hash=auth.get_password_hash(body.password),
        role="admin",
        tenant_id=tenant.id,
        is_active=True,
    )
    db.add(user)
    db.flush()

    db.add(
        StoreSettings(
            tenant_id=tenant.id,
            store_name=body.business_name.strip(),
            store_phone=body.phone.strip() or None,
            store_location=None,
        )
    )

    billing_service.create_trial_subscription(db, tenant, sync_firestore=False)
    db.commit()
    db.refresh(user)
    db.refresh(tenant)
    logger.info("Registered tenant %s user %s", tenant_uid, user.username)

    security_payload = {
        "tenant_uid": tenant_uid,
        "business_name": tenant.name,
        "owner_email": email_norm,
        "subscription_status": "trial",
        "trial_ends_at": trial_end.isoformat() + "Z",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    run_in_background(
        "register-firestore",
        _register_cloud_sync,
        tenant.id,
        tenant_uid,
        security_payload,
    )
    return _auth_response_with_cookie(_issue_tokens(db, user, tenant))


@router.post("/login")
def auth_login(request: Request, body: LoginBody, db: Session = Depends(get_db)):
    _rate_limit(request, "login", max_calls=40, window_sec=60)
    email_norm = body.email.strip().lower()
    user = auth.get_user_by_email(db, email_norm) or auth.get_user_by_username(db, email_norm)
    if not user or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    tenant = None
    if user.tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    return _auth_response_with_cookie(_issue_tokens(db, user, tenant))


@router.post("/refresh")
def auth_refresh(request: Request, body: RefreshBody, db: Session = Depends(get_db)):
    _rate_limit(request, "refresh", max_calls=60, window_sec=60)
    h = auth.hash_token(body.refresh_token.strip())
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == h).first()
    if not row or row.revoked_at is not None or row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    row.revoked_at = datetime.utcnow()
    db.flush()
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first() if user.tenant_id else None
    if tenant and tenant.tenant_uid:
        remote = fetch_tenant_subscription(tenant.tenant_uid)
        if remote and remote.get("subscription_status"):
            tenant.subscription_status = str(remote["subscription_status"])[:32]
            tenant.last_subscription_verified_at = datetime.utcnow()
    return _auth_response_with_cookie(_issue_tokens(db, user, tenant))


@router.post("/logout")
def auth_logout(body: LogoutBody, db: Session = Depends(get_db)):
    if body.refresh_token:
        h = auth.hash_token(body.refresh_token.strip())
        row = db.query(RefreshToken).filter(RefreshToken.token_hash == h).first()
        if row and row.revoked_at is None:
            row.revoked_at = datetime.utcnow()
            db.commit()
    response = JSONResponse(content={"ok": True})
    auth.clear_access_cookie(response)
    return response


@router.get("/verify", response_model=VerifyResponse)
def auth_verify(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = auth.decode_access_token(token)
    except JWTError:
        return VerifyResponse(valid=False)
    username = payload.get("sub")
    if not username:
        return VerifyResponse(valid=False)
    user = auth.get_user_by_username(db, username)
    if not user or not user.is_active:
        return VerifyResponse(valid=False)
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first() if user.tenant_id else None
    if tenant and tenant.tenant_uid:
        remote = fetch_tenant_subscription(tenant.tenant_uid)
        if remote and remote.get("subscription_status"):
            tenant.subscription_status = str(remote["subscription_status"])[:32]
            tenant.last_subscription_verified_at = datetime.utcnow()
            db.commit()
    return VerifyResponse(
        valid=True,
        user_id=user.id,
        tenant_id=user.tenant_id,
        tenant_uid=tenant.tenant_uid if tenant else None,
        subscription_status=_subscription_effective(db, tenant),
        trial_ends_at=tenant.trial_ends_at if tenant else None,
        role=user.role,
        username=user.username,
        last_verified_at=tenant.last_subscription_verified_at if tenant else None,
    )


def _build_reset_email(reset_url: str, owner_name: Optional[str]) -> tuple[str, str, str]:
    """Build (subject, plain_text, html) for a password-reset email."""
    name = (owner_name or "there").strip()
    brand = PLATFORM_BRAND_NAME
    subject = f"Reset your {brand} password"
    plain = (
        f"Hi {name},\n\n"
        f"We received a request to reset your {brand} password.\n\n"
        f"Click the link below to choose a new password. It expires in 24 hours:\n"
        f"{reset_url}\n\n"
        "If you didn't request this, you can ignore this email — your password "
        "won't change.\n\n"
        f"— {brand}"
    )
    html = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1a1a2e;">
    <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:12px;padding:32px 28px;box-shadow:0 2px 6px rgba(0,0,0,0.05);">
      <h2 style="margin:0 0 8px;font-size:22px;color:#1a1a2e;">Reset your password</h2>
      <p style="margin:0 0 16px;color:#374151;line-height:1.5;">Hi {name},</p>
      <p style="margin:0 0 20px;color:#374151;line-height:1.5;">
        We received a request to reset your {brand} password. Click the button
        below to choose a new one. The link is valid for <strong>24 hours</strong>.
      </p>
      <p style="margin:24px 0;text-align:center;">
        <a href="{reset_url}"
           style="display:inline-block;background:#0a0a0a;color:#ffffff;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;">
          Choose a new password
        </a>
      </p>
      <p style="margin:0 0 8px;color:#6b7280;font-size:13px;line-height:1.5;">
        Or paste this URL into your browser:
      </p>
      <p style="margin:0 0 24px;word-break:break-all;font-size:13px;">
        <a href="{reset_url}" style="color:#2563eb;">{reset_url}</a>
      </p>
      <p style="margin:0;color:#6b7280;font-size:13px;line-height:1.5;">
        If you didn't request this, you can safely ignore this email —
        your password won't change.
      </p>
    </div>
    <p style="text-align:center;color:#9ca3af;font-size:12px;margin:16px 0 0;">— {brand}</p>
    <p style="text-align:center;color:#9ca3af;font-size:12px;margin:4px 0 0;font-style:italic;">{PLATFORM_MOTTO}</p>
  </body>
</html>"""
    return subject, plain, html


def _send_reset_email(user: User, reset_url: str) -> None:
    email_svc = EmailService()
    if email_svc.is_configured() and user.email:
        try:
            subject, plain, html = _build_reset_email(reset_url, user.full_name)
            sent = email_svc.send_email(
                to_email=user.email,
                subject=subject,
                body=plain,
                html_body=html,
            )
            if sent:
                logger.info("Password reset email sent user_id=%s", user.id)
            else:
                logger.error(
                    "Password reset token issued for user_id=%s but email send FAILED. "
                    "Operator can use the reset URL: %s",
                    user.id,
                    reset_url,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Password reset email crashed for user_id=%s. URL: %s",
                user.id,
                reset_url,
            )
    else:
        logger.warning(
            "Password reset token issued for user_id=%s but SMTP is not "
            "configured. Operator must share this URL with the user manually: %s",
            user.id,
            reset_url,
        )


@router.post("/forgot-password")
def auth_forgot_password(request: Request, body: ForgotPasswordBody, db: Session = Depends(get_db)):
    """Issue a one-time reset token bound to each matching active user.

    Always returns the same generic 200 response, regardless of whether
    the email exists or whether SMTP succeeded, so callers can't enumerate
    valid emails. Each token is hashed and tied to an exact user_id.
    """
    _rate_limit(request, "forgot", max_calls=10, window_sec=600)

    generic = {
        "ok": True,
        "message": "If that email exists, reset instructions were sent.",
    }

    email_norm = body.email.strip().lower()
    users = _active_users_by_email(db, email_norm)
    if not users:
        # Spend roughly the same time as the email-issue branch so we don't
        # leak existence via timing — cheap because hash_token is fast.
        auth.hash_token(secrets.token_urlsafe(32))
        return generic

    for user in users:
        raw = _issue_reset_token_for_user(db, user)
        reset_url = f"{WEB_PUBLIC_URL}/reset-password?token={raw}"
        _send_reset_email(user, reset_url)

    db.commit()
    return generic


@router.get("/reset-password/validate")
def auth_validate_reset_token(
    token: str = Query("", min_length=0),
    db: Session = Depends(get_db),
):
    """Return masked email + store name derived only from the reset token.

    Never trusts client-supplied user/store/tenant/email. Invalid/expired/used
    tokens return valid=false with null display fields (no enumeration detail).
    """
    invalid = {"valid": False, "maskedEmail": None, "storeName": None}
    row, user = _lookup_reset_token(db, token)
    if not row or not user:
        return _auth_no_store_json(invalid)
    return _auth_no_store_json(
        {
            "valid": True,
            "maskedEmail": _mask_email(user.email or ""),
            "storeName": _store_name_for_user(db, user),
        }
    )


@router.post("/reset-password")
def auth_reset_password(body: ResetPasswordBody, db: Session = Depends(get_db)):
    """Change password for the user bound to the token only.

    Extra client fields (user_id, store_id, tenant_id, email) are ignored via
    model_config extra='ignore'. Identity is never taken from the request body
    beyond the opaque reset token.
    """
    if body.confirm_password is not None and body.confirm_password != body.new_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    row, user = _lookup_reset_token(db, body.token)
    if not row or not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user.password_hash = auth.get_password_hash(body.new_password)
    row.used_at = datetime.utcnow()
    _invalidate_unused_reset_tokens(db, user.id, except_id=row.id)
    for rt in (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .all()
    ):
        rt.revoked_at = datetime.utcnow()
    db.commit()
    return _auth_no_store_json({"ok": True})
