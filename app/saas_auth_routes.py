"""SaaS authentication: register, login, refresh, logout, verify, forgot/reset password."""
from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth
from .config import WEB_PUBLIC_URL
from .database import get_db
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
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8, max_length=128)


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
    )


@router.post("/register", response_model=AuthResponse)
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

    fs_id = upsert_tenant_security_record(
        tenant_uid,
        {
            "tenant_uid": tenant_uid,
            "business_name": tenant.name,
            "owner_email": email_norm,
            "subscription_status": "trial",
            "trial_ends_at": trial_end.isoformat() + "Z",
            "created_at": datetime.utcnow().isoformat() + "Z",
        },
    )
    if fs_id:
        tenant.firestore_doc_id = fs_id
    billing_service.create_trial_subscription(db, tenant)
    db.commit()
    db.refresh(user)
    db.refresh(tenant)
    logger.info("Registered tenant %s user %s", tenant_uid, user.username)
    return _issue_tokens(db, user, tenant)


@router.post("/login", response_model=AuthResponse)
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
    return _issue_tokens(db, user, tenant)


@router.post("/refresh", response_model=AuthResponse)
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
    return _issue_tokens(db, user, tenant)


@router.post("/logout")
def auth_logout(body: LogoutBody, db: Session = Depends(get_db)):
    if body.refresh_token:
        h = auth.hash_token(body.refresh_token.strip())
        row = db.query(RefreshToken).filter(RefreshToken.token_hash == h).first()
        if row and row.revoked_at is None:
            row.revoked_at = datetime.utcnow()
            db.commit()
    return {"ok": True}


@router.get("/verify", response_model=VerifyResponse)
def auth_verify(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
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
    subject = "Reset your doposai password"
    plain = (
        f"Hi {name},\n\n"
        "We received a request to reset your doposai password.\n\n"
        f"Click the link below to choose a new password. It expires in 24 hours:\n"
        f"{reset_url}\n\n"
        "If you didn't request this, you can ignore this email — your password "
        "won't change.\n\n"
        "— doposai"
    )
    html = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1a1a2e;">
    <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:12px;padding:32px 28px;box-shadow:0 2px 6px rgba(0,0,0,0.05);">
      <h2 style="margin:0 0 8px;font-size:22px;color:#1a1a2e;">Reset your password</h2>
      <p style="margin:0 0 16px;color:#374151;line-height:1.5;">Hi {name},</p>
      <p style="margin:0 0 20px;color:#374151;line-height:1.5;">
        We received a request to reset your doposai password. Click the button
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
    <p style="text-align:center;color:#9ca3af;font-size:12px;margin:16px 0 0;">— doposai</p>
  </body>
</html>"""
    return subject, plain, html


@router.post("/forgot-password")
def auth_forgot_password(request: Request, body: ForgotPasswordBody, db: Session = Depends(get_db)):
    """Issue a one-time reset token and email it to the account holder.

    Always returns the same generic 200 response, regardless of whether
    the email exists or whether SMTP succeeded, so callers can't enumerate
    valid emails. The token (and any send failure) is logged server-side
    for operator visibility.
    """
    _rate_limit(request, "forgot", max_calls=10, window_sec=600)

    generic = {
        "ok": True,
        "message": "If that email exists, reset instructions were sent.",
    }

    email_norm = body.email.strip().lower()
    user = auth.get_user_by_email(db, email_norm)
    if not user:
        # Spend roughly the same time as the email-issue branch so we don't
        # leak existence via timing — cheap because hash_token is fast.
        auth.hash_token(secrets.token_urlsafe(32))
        return generic

    raw = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=auth.hash_token(raw),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
    )
    db.commit()

    reset_url = f"{WEB_PUBLIC_URL}/reset-password?token={raw}"

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
        # SMTP not configured — token is still valid; the operator can copy
        # the URL out of the logs to share with the user manually.
        logger.warning(
            "Password reset token issued for user_id=%s but SMTP is not "
            "configured. Operator must share this URL with the user manually: %s",
            user.id,
            reset_url,
        )

    return generic


@router.post("/reset-password")
def auth_reset_password(body: ResetPasswordBody, db: Session = Depends(get_db)):
    h = auth.hash_token(body.token.strip())
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == h, PasswordResetToken.used_at.is_(None))
        .first()
    )
    if not row or row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="User not found")
    user.password_hash = auth.get_password_hash(body.new_password)
    row.used_at = datetime.utcnow()
    for rt in (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .all()
    ):
        rt.revoked_at = datetime.utcnow()
    db.commit()
    return {"ok": True}
