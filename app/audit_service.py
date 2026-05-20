"""
Enterprise audit trail logging.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from .enterprise_models import AuditLog
from .models import User


def _serialize(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


def client_meta(request: Optional[Request]) -> tuple[Optional[str], Optional[str]]:
    if request is None:
        return None, None
    device = request.headers.get("X-Device-Id") or request.headers.get("User-Agent")
    ip = request.client.host if request.client else None
    return device, ip


def log_audit(
    db: Session,
    *,
    user: Optional[User],
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    old_value: Any = None,
    new_value: Any = None,
    tenant_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    request: Optional[Request] = None,
) -> AuditLog:
    device, ip = client_meta(request)
    entry = AuditLog(
        tenant_id=tenant_id if tenant_id is not None else (user.tenant_id if user else None),
        branch_id=branch_id,
        user_id=user.id if user else None,
        username=user.username if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=_serialize(old_value),
        new_value=_serialize(new_value),
        device=device[:120] if device else None,
        ip_address=ip,
    )
    db.add(entry)
    return entry
