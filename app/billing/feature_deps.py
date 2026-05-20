"""FastAPI dependencies for plan-based feature gates."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_active_user
from ..database import get_db
from ..models import User
from ..quotation_models import Tenant
from . import service as billing_service
from .features import (
    Feature,
    feature_denied_payload,
    resolve_effective_plan,
    tenant_has_feature,
)


def _tenant_for_user(db: Session, user: User) -> Tenant | None:
    if not user.tenant_id:
        return None
    return db.query(Tenant).filter(Tenant.id == user.tenant_id).first()


def require_feature(feature: Feature):
    """Dependency: active user must have [feature] on their subscription plan (trial = all)."""

    def _checker(
        db: Session = Depends(get_db),
        user: User = Depends(get_current_active_user),
    ) -> User:
        tenant = _tenant_for_user(db, user)
        if tenant is None:
            return user
        sub = billing_service.get_or_create_subscription(db, tenant)
        if tenant_has_feature(db, tenant, feature, sub):
            return user
        plan = resolve_effective_plan(sub)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=feature_denied_payload(feature, plan),
        )

    return _checker
