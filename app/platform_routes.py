"""Platform-owner APIs: list all SaaS tenants (businesses using the POS)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth
from .config import PLATFORM_OWNER_USERNAMES
from .database import get_db
from .models import StoreSettings, User
from .quotation_models import Tenant

router = APIRouter(prefix="/api/platform", tags=["platform"])


def is_platform_owner_user(user: User) -> bool:
    if not user.is_active or user.role != "admin":
        return False
    if not PLATFORM_OWNER_USERNAMES:
        return False
    return user.username.strip().lower() in PLATFORM_OWNER_USERNAMES


def require_platform_owner(
    user: User = Depends(auth.get_current_active_user),
) -> User:
    if not PLATFORM_OWNER_USERNAMES:
        raise HTTPException(
            status_code=403,
            detail="Platform owner access is not configured. Set PLATFORM_OWNER_USERNAMES on the server.",
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
    trial_ends_at: Optional[datetime] = None
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
        rows.append(
            PlatformTenantRow(
                id=t.id,
                tenant_uid=t.tenant_uid,
                business_name=t.name,
                owner_name=t.owner_name,
                phone=t.phone,
                email=t.email,
                subscription_status=t.subscription_status or "trial",
                trial_ends_at=t.trial_ends_at,
                is_active=bool(t.is_active),
                created_at=t.created_at,
                user_count=int(user_count),
                admin_usernames=", ".join(admin_names) if admin_names else "—",
                store_display_name=store_display,
            )
        )
    return rows
