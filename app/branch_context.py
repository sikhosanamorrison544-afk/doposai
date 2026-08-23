"""
Active branch context resolution and membership checks.

Precedence (Section 13):
1. Explicit X-Branch-Id header (or explicit query) — fails hard if invalid
2. Server-validated token/session claim (bid / bscope)
3. UserBranch default membership
4. Legacy User.branch_id
5. Tenant Main Branch

Rules:
- Tenant always comes from the authenticated user.
- Branch must belong to that tenant.
- User must have access (owner/admin OR active UserBranch OR legacy User.branch_id).
- Invalid / unauthorized explicit branch → controlled 400/403/404, never silent fallback.
- Clients must not treat localStorage as authorization.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from .branch_models import UserBranch
from .enterprise_models import Branch
from .models import User
from .permissions import is_admin_level

logger = logging.getLogger(__name__)

HEADER_BRANCH_ID = "X-Branch-Id"


@dataclass(frozen=True)
class BranchContext:
    tenant_id: Optional[int]
    branch_id: Optional[int]
    branch: Optional[Branch]
    source: str  # header | query | token | membership_default | user_branch_id | main | none
    scope: str = "branch"  # branch | all

    def log_extra(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "branch_id": self.branch_id,
            "branch_source": self.source,
            "branch_scope": self.scope,
        }


def _branch_for_tenant(db: Session, branch_id: int, tenant_id: Optional[int]) -> Optional[Branch]:
    q = db.query(Branch).filter(Branch.id == int(branch_id))
    if tenant_id is None:
        q = q.filter(Branch.tenant_id.is_(None))
    else:
        q = q.filter(Branch.tenant_id == int(tenant_id))
    return q.first()


def user_has_branch_access(db: Session, user: User, branch_id: int) -> bool:
    """Owner/admin: any branch in tenant (incl. inactive for history). Others: active membership.

    Single-store compatibility: users with no memberships and no legacy branch_id
    may access the tenant Main Branch only.
    """
    br = _branch_for_tenant(db, branch_id, user.tenant_id)
    if br is None:
        return False
    if is_admin_level(user):
        return True
    if not bool(br.is_active):
        return False
    m = (
        db.query(UserBranch)
        .filter(
            UserBranch.user_id == user.id,
            UserBranch.branch_id == int(branch_id),
            UserBranch.is_active.is_(True),
        )
        .first()
    )
    if m is not None:
        if user.tenant_id is not None and m.tenant_id is not None and m.tenant_id != user.tenant_id:
            return False
        return True
    if getattr(user, "branch_id", None) is not None and int(user.branch_id) == int(branch_id):
        return True
    # Implicit Main Branch for users not yet assigned (Section 13 compatibility)
    has_any = (
        db.query(UserBranch.id)
        .filter(UserBranch.user_id == user.id, UserBranch.is_active.is_(True))
        .first()
        is not None
    )
    if not has_any and getattr(user, "branch_id", None) is None and br.is_default and br.is_active:
        return True
    return False


def list_accessible_branch_ids(
    db: Session, user: User, *, include_inactive: bool = False
) -> List[int]:
    q = db.query(Branch)
    if user.tenant_id is None:
        q = q.filter(Branch.tenant_id.is_(None))
    else:
        q = q.filter(Branch.tenant_id == user.tenant_id)
    if not include_inactive:
        q = q.filter(Branch.is_active.is_(True))
    if is_admin_level(user):
        return [b.id for b in q.order_by(Branch.id).all()]
    allowed: set[int] = set()
    for m in (
        db.query(UserBranch)
        .filter(UserBranch.user_id == user.id, UserBranch.is_active.is_(True))
        .all()
    ):
        allowed.add(int(m.branch_id))
    if getattr(user, "branch_id", None) is not None:
        allowed.add(int(user.branch_id))
    if not allowed:
        # Implicit Main Branch for unassigned single-store users
        main = (
            q.filter(Branch.is_default.is_(True)).order_by(Branch.id.asc()).first()
        )
        if main is not None:
            return [main.id]
        return []
    return [b.id for b in q.filter(Branch.id.in_(allowed)).order_by(Branch.id).all()]


def default_branch_id(db: Session, user: User) -> Optional[int]:
    """Prefer membership is_default, then User.branch_id, then tenant main/default branch."""
    m = (
        db.query(UserBranch)
        .filter(
            UserBranch.user_id == user.id,
            UserBranch.is_active.is_(True),
            UserBranch.is_default.is_(True),
        )
        .first()
    )
    if m is not None:
        return int(m.branch_id)
    if getattr(user, "branch_id", None) is not None:
        return int(user.branch_id)
    q = db.query(Branch)
    if user.tenant_id is None:
        q = q.filter(Branch.tenant_id.is_(None))
    else:
        q = q.filter(Branch.tenant_id == user.tenant_id)
    main = (
        q.filter(Branch.is_active.is_(True), Branch.is_default.is_(True))
        .order_by(Branch.id.asc())
        .first()
    )
    if main is not None:
        return int(main.id)
    any_b = q.filter(Branch.is_active.is_(True)).order_by(Branch.id.asc()).first()
    return int(any_b.id) if any_b else None


def require_branch_access(db: Session, user: User, branch_id: int) -> Branch:
    br = _branch_for_tenant(db, branch_id, user.tenant_id)
    if br is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found for this tenant",
        )
    if not user_has_branch_access(db, user, branch_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No access to this branch",
        )
    return br


def _token_claims_from_user(user: User) -> tuple[Optional[int], Optional[str]]:
    bid = getattr(user, "_token_branch_id", None)
    scope = getattr(user, "_token_branch_scope", None)
    return (int(bid) if bid is not None else None), scope


def resolve_branch_context(
    db: Session,
    user: User,
    *,
    header_branch_id: Optional[str] = None,
    query_branch_id: Optional[int] = None,
    token_branch_id: Optional[int] = None,
    token_scope: Optional[str] = None,
    require_branch: bool = False,
) -> BranchContext:
    """
    Resolve active branch.

    Explicit header/query fails hard (no silent fallback).
    Token claim is validated; if revoked/invalid, fall through to membership defaults.
    """
    tid = user.tenant_id
    if token_branch_id is None and token_scope is None:
        tb, ts = _token_claims_from_user(user)
        token_branch_id = tb if token_branch_id is None else token_branch_id
        token_scope = ts if token_scope is None else token_scope

    if (token_scope or "").strip().lower() == "all" and not (
        header_branch_id or query_branch_id is not None
    ):
        if is_admin_level(user):
            return BranchContext(
                tenant_id=tid, branch_id=None, branch=None, source="token", scope="all"
            )

    explicit: Optional[int] = None
    source = "none"
    if header_branch_id is not None and str(header_branch_id).strip() != "":
        try:
            explicit = int(str(header_branch_id).strip())
            source = "header"
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Branch-Id",
            ) from e
    elif query_branch_id is not None:
        explicit = int(query_branch_id)
        source = "query"

    if explicit is not None:
        br = _branch_for_tenant(db, explicit, tid)
        if br is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found for this tenant",
            )
        if not br.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot select an inactive branch",
            )
        if not user_has_branch_access(db, user, explicit):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No access to this branch",
            )
        logger.info(
            "branch_context tenant_id=%s branch_id=%s user_id=%s source=%s",
            tid,
            br.id,
            user.id,
            source,
        )
        return BranchContext(
            tenant_id=tid, branch_id=br.id, branch=br, source=source, scope="branch"
        )

    # Token claim preference (validated; soft fallback if revoked)
    if token_branch_id is not None:
        br = _branch_for_tenant(db, int(token_branch_id), tid)
        if br is not None and br.is_active and user_has_branch_access(db, user, br.id):
            return BranchContext(
                tenant_id=tid,
                branch_id=br.id,
                branch=br,
                source="token",
                scope="branch",
            )

    bid = default_branch_id(db, user)
    if bid is None:
        if require_branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No branch available for this user",
            )
        return BranchContext(
            tenant_id=tid, branch_id=None, branch=None, source="none", scope="branch"
        )
    br = require_branch_access(db, user, bid)
    src = "membership_default"
    if getattr(user, "branch_id", None) == bid:
        m = (
            db.query(UserBranch)
            .filter(
                UserBranch.user_id == user.id,
                UserBranch.branch_id == bid,
                UserBranch.is_active.is_(True),
                UserBranch.is_default.is_(True),
            )
            .first()
        )
        src = "membership_default" if m else "user_branch_id"
    if br.is_default:
        mdef = (
            db.query(UserBranch)
            .filter(
                UserBranch.user_id == user.id,
                UserBranch.branch_id == bid,
                UserBranch.is_default.is_(True),
            )
            .first()
        )
        if mdef is None and getattr(user, "branch_id", None) != bid:
            src = "main"
    return BranchContext(
        tenant_id=tid, branch_id=br.id, branch=br, source=src, scope="branch"
    )


def parse_branch_header(
    x_branch_id: Optional[str] = Header(None, alias=HEADER_BRANCH_ID),
) -> Optional[str]:
    return x_branch_id


def sale_branch_must_match_refund(
    sale_branch_id: Optional[int], refund_branch_id: Optional[int]
) -> None:
    """Refund stock restoration must target the sale's branch."""
    if sale_branch_id is None and refund_branch_id is None:
        return
    if sale_branch_id != refund_branch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refund branch must match the original sale branch",
        )


def ensure_offline_branch_id(payload_branch_id: Optional[int]) -> int:
    """Offline payloads must carry an explicit originating branch."""
    if payload_branch_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Offline transaction requires originating branch_id",
        )
    return int(payload_branch_id)
