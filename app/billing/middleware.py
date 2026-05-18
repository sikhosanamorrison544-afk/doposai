"""Optional FastAPI dependency: block POS when subscription inactive (online checks)."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_active_user
from ..database import get_db
from ..models import User
from ..quotation_models import Tenant
from . import service as billing_service


def require_subscription_access(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
) -> User:
    """
    Use on sensitive online-only routes. Offline POS uses cached JWT + grace in the app.
    """
    if not user.tenant_id:
        return user
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    if not tenant:
        return user
    sub = billing_service.get_or_create_subscription(db, tenant)
    _, allowed, _ = billing_service.effective_status(sub, tenant)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Subscription inactive. Renew at /billing",
        )
    return user
