"""HTTP middleware: enforce plan features on API routes (after JWT present)."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from jose import JWTError, jwt

from ..auth import ALGORITHM, SECRET_KEY, get_user_by_username
from ..database import SessionLocal
from ..models import User
from ..quotation_models import Tenant
from . import service as billing_service
from .features import (
    feature_denied_payload,
    feature_for_api_path,
    resolve_effective_plan,
    tenant_has_feature,
)

logger = logging.getLogger(__name__)

_EXEMPT_PREFIXES = (
    "/api/auth",
    "/api/subscriptions",
    "/api/billing",
    "/api/payments",
    "/auth/",
    "/health",
    "/favicon",
    "/static/",
)


def _user_from_authorization(db, auth_header: Optional[str]) -> Optional[User]:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:].strip()
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            return None
        tid_claim = payload.get("tid")
    except JWTError:
        return None
    user = get_user_by_username(db, username=username)
    if not user or not user.is_active:
        return None
    if user.tenant_id is not None and tid_claim is not None:
        if int(tid_claim) != int(user.tenant_id):
            return None
    return user


class PlanFeatureMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        feature = feature_for_api_path(path)
        if feature is None:
            return await call_next(request)

        user = None
        db = SessionLocal()
        try:
            user = _user_from_authorization(db, request.headers.get("authorization"))
            if user is None:
                return await call_next(request)
            if not user.tenant_id:
                return await call_next(request)
            tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
            if not tenant:
                return await call_next(request)
            sub = billing_service.get_or_create_subscription(db, tenant)
            if tenant_has_feature(db, tenant, feature, sub):
                return await call_next(request)
            plan = resolve_effective_plan(sub)
            payload = feature_denied_payload(feature, plan)
            return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=payload)
        except Exception as e:
            logger.warning("PlanFeatureMiddleware error: %s", e)
            return await call_next(request)
        finally:
            db.close()
