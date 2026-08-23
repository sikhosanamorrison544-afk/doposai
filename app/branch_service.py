"""
Section 13 — branch management, membership, and switching services.

Stock SoT remains Product.stock_qty (Section 14 cutover).
JournalEntry stays reference-derived. StoreSettings stays tenant-wide.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from .audit_service import log_audit
from .branch_models import UserBranch
from .enterprise_models import Branch, BranchProductStock
from .models import (
    CashMovement,
    CashierShift,
    Expense,
    Product,
    Refund,
    Sale,
    User,
    Withdrawal,
)
from .permissions import (
    Perm,
    has_permission,
    is_admin_level,
    normalize_role,
)

logger = logging.getLogger(__name__)

SCOPE_BRANCH = "branch"
SCOPE_ALL = "all"

CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_\-]{0,31}$")


def normalize_branch_code(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    code = str(raw).strip().upper()
    if not code:
        return None
    if not CODE_RE.match(code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Branch code must be 1–32 chars: A–Z, 0–9, underscore, hyphen",
        )
    return code


def normalize_branch_name(raw: str) -> str:
    name = (raw or "").strip()
    if len(name) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Branch name must be at least 2 characters",
        )
    if len(name) > 120:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Branch name must be at most 120 characters",
        )
    return name


def _tenant_branches_q(db: Session, tenant_id: Optional[int]):
    q = db.query(Branch)
    if tenant_id is None:
        return q.filter(Branch.tenant_id.is_(None))
    return q.filter(Branch.tenant_id == tenant_id)


def get_tenant_branch(db: Session, tenant_id: Optional[int], branch_id: int) -> Branch:
    br = _tenant_branches_q(db, tenant_id).filter(Branch.id == int(branch_id)).first()
    if br is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")
    return br


def branch_to_dict(br: Branch, *, staff_count: Optional[int] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": br.id,
        "tenant_id": br.tenant_id,
        "name": br.name,
        "code": br.code,
        "address": br.address,
        "phone": br.phone,
        "email": getattr(br, "email", None),
        "manager_user_id": getattr(br, "manager_user_id", None),
        "is_main": bool(br.is_default),
        "is_default": bool(br.is_default),
        "is_active": bool(br.is_active),
        "created_at": br.created_at.isoformat() if br.created_at else None,
        "updated_at": br.updated_at.isoformat() if br.updated_at else None,
    }
    if staff_count is not None:
        out["staff_count"] = staff_count
    return out


def membership_to_dict(m: UserBranch, user: Optional[User] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": m.id,
        "user_id": m.user_id,
        "branch_id": m.branch_id,
        "tenant_id": m.tenant_id,
        "role": m.role,
        "is_default": bool(m.is_default),
        "is_active": bool(m.is_active),
        "assigned_at": m.assigned_at.isoformat() if m.assigned_at else None,
        "assigned_by_id": m.assigned_by_id,
        "updated_at": m.updated_at.isoformat() if getattr(m, "updated_at", None) else None,
    }
    if user is not None:
        out["username"] = user.username
        out["full_name"] = user.full_name
        out["user_role"] = user.role
        out["user_is_active"] = bool(user.is_active)
    return out


def active_branch_summary(br: Optional[Branch]) -> Optional[Dict[str, Any]]:
    if br is None:
        return None
    return {"id": br.id, "name": br.name, "code": br.code, "is_main": bool(br.is_default)}


def count_active_staff(db: Session, branch_id: int) -> int:
    return (
        db.query(UserBranch)
        .filter(UserBranch.branch_id == branch_id, UserBranch.is_active.is_(True))
        .count()
    )


def ensure_single_main(db: Session, tenant_id: Optional[int], main_branch_id: int) -> None:
    """Clear is_default on siblings; set on target. Must run in same transaction before commit."""
    target = get_tenant_branch(db, tenant_id, main_branch_id)
    q = _tenant_branches_q(db, tenant_id).filter(Branch.id != target.id, Branch.is_default.is_(True))
    for other in q.all():
        other.is_default = False
    target.is_default = True
    target.updated_at = datetime.utcnow()
    db.flush()


def list_branches_for_user(
    db: Session,
    user: User,
    *,
    include_inactive: bool = False,
) -> List[Branch]:
    from .branch_context import list_accessible_branch_ids

    ids = list_accessible_branch_ids(db, user, include_inactive=include_inactive)
    if not ids:
        return []
    q = db.query(Branch).filter(Branch.id.in_(ids))
    if not include_inactive:
        q = q.filter(Branch.is_active.is_(True))
    return q.order_by(Branch.is_default.desc(), Branch.name.asc()).all()


def list_all_tenant_branches(
    db: Session,
    user: User,
    *,
    include_inactive: bool = True,
) -> List[Branch]:
    """Admin listing (manage view)."""
    if not (
        is_admin_level(user)
        or has_permission(user, Perm.BRANCH_VIEW)
        or has_permission(user, Perm.MANAGE_BRANCHES)
    ):
        raise HTTPException(status_code=403, detail="Permission denied: branch.view")
    q = _tenant_branches_q(db, user.tenant_id)
    if not include_inactive:
        q = q.filter(Branch.is_active.is_(True))
    return q.order_by(Branch.is_default.desc(), Branch.name.asc()).all()


def create_branch(
    db: Session,
    user: User,
    *,
    name: str,
    code: Optional[str] = None,
    address: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    manager_user_id: Optional[int] = None,
    is_main: bool = False,
    request: Optional[Request] = None,
) -> Branch:
    if not (
        has_permission(user, Perm.BRANCH_CREATE) or has_permission(user, Perm.MANAGE_BRANCHES)
    ):
        raise HTTPException(status_code=403, detail="Permission denied: branch.create")

    tid = user.tenant_id
    name_n = normalize_branch_name(name)
    code_n = normalize_branch_code(code) if code else None
    if code_n:
        clash = (
            _tenant_branches_q(db, tid)
            .filter(Branch.code == code_n)
            .first()
        )
        if clash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Branch code already exists for this tenant",
            )
    name_clash = _tenant_branches_q(db, tid).filter(Branch.name == name_n).first()
    if name_clash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Branch name already exists for this tenant",
        )

    if manager_user_id is not None:
        _require_tenant_user(db, tid, manager_user_id)

    existing_count = _tenant_branches_q(db, tid).count()
    make_main = bool(is_main) or existing_count == 0

    br = Branch(
        tenant_id=tid,
        name=name_n,
        code=code_n or (f"BR{existing_count + 1}" if existing_count else "MAIN"),
        address=(address or "").strip() or None,
        phone=(phone or "").strip() or None,
        email=(email or "").strip() or None,
        manager_user_id=manager_user_id,
        is_active=True,
        is_default=False,
    )
    # Re-normalize auto code
    br.code = normalize_branch_code(br.code)
    db.add(br)
    db.flush()
    if make_main:
        ensure_single_main(db, tid, br.id)
    log_audit(
        db,
        user=user,
        action="branch.created",
        entity_type="branch",
        entity_id=br.id,
        new_value=branch_to_dict(br),
        branch_id=br.id,
        request=request,
    )
    db.flush()
    return br


def update_branch(
    db: Session,
    user: User,
    branch_id: int,
    *,
    name: Optional[str] = None,
    code: Optional[str] = None,
    address: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    manager_user_id: Optional[int] = ...,  # type: ignore
    is_main: Optional[bool] = None,
    request: Optional[Request] = None,
) -> Branch:
    if not (
        has_permission(user, Perm.BRANCH_UPDATE) or has_permission(user, Perm.MANAGE_BRANCHES)
    ):
        raise HTTPException(status_code=403, detail="Permission denied: branch.update")

    br = get_tenant_branch(db, user.tenant_id, branch_id)
    old = branch_to_dict(br)

    if name is not None:
        name_n = normalize_branch_name(name)
        clash = (
            _tenant_branches_q(db, user.tenant_id)
            .filter(Branch.name == name_n, Branch.id != br.id)
            .first()
        )
        if clash:
            raise HTTPException(status_code=409, detail="Branch name already exists for this tenant")
        br.name = name_n
    if code is not None:
        code_n = normalize_branch_code(code)
        if code_n:
            clash = (
                _tenant_branches_q(db, user.tenant_id)
                .filter(Branch.code == code_n, Branch.id != br.id)
                .first()
            )
            if clash:
                raise HTTPException(status_code=409, detail="Branch code already exists for this tenant")
        br.code = code_n
    if address is not None:
        br.address = address.strip() or None
    if phone is not None:
        br.phone = phone.strip() or None
    if email is not None:
        br.email = email.strip() or None
    if manager_user_id is not ...:
        if manager_user_id is not None:
            _require_tenant_user(db, user.tenant_id, int(manager_user_id))
        br.manager_user_id = manager_user_id

    if is_main is True:
        ensure_single_main(db, user.tenant_id, br.id)
        log_audit(
            db,
            user=user,
            action="branch.main_changed",
            entity_type="branch",
            entity_id=br.id,
            old_value=old,
            new_value=branch_to_dict(br),
            branch_id=br.id,
            request=request,
        )
    elif is_main is False and br.is_default:
        raise HTTPException(
            status_code=400,
            detail="Cannot clear main flag without designating another main branch",
        )

    br.updated_at = datetime.utcnow()
    log_audit(
        db,
        user=user,
        action="branch.updated",
        entity_type="branch",
        entity_id=br.id,
        old_value=old,
        new_value=branch_to_dict(br),
        branch_id=br.id,
        request=request,
    )
    db.flush()
    return br


def branch_has_history(db: Session, branch_id: int) -> bool:
    checks = [
        db.query(Sale.id).filter(Sale.branch_id == branch_id).first(),
        db.query(CashierShift.id).filter(CashierShift.branch_id == branch_id).first(),
        db.query(Refund.id).filter(Refund.branch_id == branch_id).first(),
        db.query(Expense.id).filter(Expense.branch_id == branch_id).first(),
        db.query(Withdrawal.id).filter(Withdrawal.branch_id == branch_id).first(),
        db.query(CashMovement.id).filter(CashMovement.branch_id == branch_id).first(),
        db.query(BranchProductStock.id).filter(BranchProductStock.branch_id == branch_id).first(),
    ]
    return any(c is not None for c in checks)


def activate_branch(
    db: Session, user: User, branch_id: int, *, request: Optional[Request] = None
) -> Branch:
    if not (
        has_permission(user, Perm.BRANCH_UPDATE) or has_permission(user, Perm.MANAGE_BRANCHES)
    ):
        raise HTTPException(status_code=403, detail="Permission denied: branch.update")
    br = get_tenant_branch(db, user.tenant_id, branch_id)
    br.is_active = True
    br.updated_at = datetime.utcnow()
    log_audit(
        db,
        user=user,
        action="branch.activated",
        entity_type="branch",
        entity_id=br.id,
        branch_id=br.id,
        request=request,
    )
    db.flush()
    return br


def deactivate_branch(
    db: Session, user: User, branch_id: int, *, request: Optional[Request] = None
) -> Branch:
    if not (
        has_permission(user, Perm.BRANCH_DEACTIVATE) or has_permission(user, Perm.MANAGE_BRANCHES)
    ):
        raise HTTPException(status_code=403, detail="Permission denied: branch.deactivate")
    br = get_tenant_branch(db, user.tenant_id, branch_id)
    active_others = (
        _tenant_branches_q(db, user.tenant_id)
        .filter(Branch.is_active.is_(True), Branch.id != br.id)
        .count()
    )
    if br.is_default and active_others == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot deactivate the only active main branch",
        )
    if br.is_default and active_others > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Promote another branch to main before deactivating the main branch",
        )

    from .models import CashierShift, Refund
    from sqlalchemy import func

    open_shifts = (
        db.query(CashierShift.id)
        .filter(CashierShift.branch_id == br.id, CashierShift.end_time.is_(None))
        .count()
    )
    if open_shifts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot deactivate branch with open shifts",
        )
    pending_refunds = (
        db.query(Refund.id)
        .filter(Refund.branch_id == br.id, Refund.status == "pending")
        .count()
    )
    if pending_refunds:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot deactivate branch with pending refunds",
        )
    stock_total = (
        db.query(func.coalesce(func.sum(BranchProductStock.stock_qty), 0))
        .filter(BranchProductStock.branch_id == br.id)
        .scalar()
    )
    if float(stock_total or 0) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot deactivate branch with non-zero stock; transfer or adjust first",
        )

    br.is_active = False
    br.updated_at = datetime.utcnow()
    log_audit(
        db,
        user=user,
        action="branch.deactivated",
        entity_type="branch",
        entity_id=br.id,
        branch_id=br.id,
        new_value={"preserved_history": branch_has_history(db, br.id)},
        request=request,
    )
    db.flush()
    return br


def _require_tenant_user(db: Session, tenant_id: Optional[int], user_id: int) -> User:
    u = db.query(User).filter(User.id == int(user_id)).first()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    if tenant_id is None:
        if u.tenant_id is not None:
            raise HTTPException(status_code=403, detail="User belongs to another tenant")
    elif u.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="User belongs to another tenant")
    return u


def _clear_other_defaults(db: Session, user_id: int, keep_membership_id: Optional[int] = None) -> None:
    q = db.query(UserBranch).filter(
        UserBranch.user_id == user_id,
        UserBranch.is_default.is_(True),
        UserBranch.is_active.is_(True),
    )
    if keep_membership_id is not None:
        q = q.filter(UserBranch.id != keep_membership_id)
    for m in q.all():
        m.is_default = False
        if hasattr(m, "updated_at"):
            m.updated_at = datetime.utcnow()


def assign_staff(
    db: Session,
    actor: User,
    branch_id: int,
    *,
    user_id: int,
    role: str = "cashier",
    is_default: bool = False,
    request: Optional[Request] = None,
) -> UserBranch:
    if not (
        has_permission(actor, Perm.BRANCH_STAFF_ASSIGN)
        or has_permission(actor, Perm.MANAGE_BRANCHES)
        or has_permission(actor, Perm.MANAGE_USERS)
    ):
        raise HTTPException(status_code=403, detail="Permission denied: branch.staff.assign")

    br = get_tenant_branch(db, actor.tenant_id, branch_id)
    if not br.is_active:
        raise HTTPException(status_code=400, detail="Cannot assign staff to an inactive branch")

    target = _require_tenant_user(db, actor.tenant_id, user_id)
    if not target.is_active:
        raise HTTPException(status_code=400, detail="Cannot assign an inactive user")

    role_n = (role or "cashier").strip().lower()
    existing = (
        db.query(UserBranch)
        .filter(UserBranch.user_id == target.id, UserBranch.branch_id == br.id)
        .first()
    )
    if existing:
        existing.is_active = True
        existing.role = role_n
        existing.assigned_by_id = actor.id
        if hasattr(existing, "updated_at"):
            existing.updated_at = datetime.utcnow()
        if is_default:
            _clear_other_defaults(db, target.id, keep_membership_id=existing.id)
            existing.is_default = True
            target.branch_id = br.id
        m = existing
        action = "branch.staff.updated"
    else:
        m = UserBranch(
            tenant_id=actor.tenant_id,
            user_id=target.id,
            branch_id=br.id,
            role=role_n,
            is_default=False,
            is_active=True,
            assigned_by_id=actor.id,
        )
        db.add(m)
        db.flush()
        if is_default:
            _clear_other_defaults(db, target.id, keep_membership_id=m.id)
            m.is_default = True
            target.branch_id = br.id
        action = "branch.staff.assigned"

    log_audit(
        db,
        user=actor,
        action=action,
        entity_type="user_branch",
        entity_id=m.id,
        branch_id=br.id,
        new_value={
            "user_id": target.id,
            "branch_id": br.id,
            "role": role_n,
            "is_default": bool(m.is_default),
        },
        request=request,
    )
    db.flush()
    return m


def update_staff_membership(
    db: Session,
    actor: User,
    branch_id: int,
    user_id: int,
    *,
    role: Optional[str] = None,
    is_default: Optional[bool] = None,
    is_active: Optional[bool] = None,
    request: Optional[Request] = None,
) -> UserBranch:
    if not (
        has_permission(actor, Perm.BRANCH_STAFF_ASSIGN)
        or has_permission(actor, Perm.MANAGE_BRANCHES)
        or has_permission(actor, Perm.MANAGE_USERS)
    ):
        raise HTTPException(status_code=403, detail="Permission denied: branch.staff.assign")

    br = get_tenant_branch(db, actor.tenant_id, branch_id)
    target = _require_tenant_user(db, actor.tenant_id, user_id)
    m = (
        db.query(UserBranch)
        .filter(UserBranch.user_id == target.id, UserBranch.branch_id == br.id)
        .first()
    )
    if m is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    old = membership_to_dict(m)
    if role is not None:
        m.role = role.strip().lower()
    if is_active is False:
        m.is_active = False
        m.is_default = False
    elif is_active is True:
        if not target.is_active:
            raise HTTPException(status_code=400, detail="Cannot activate membership for inactive user")
        m.is_active = True
    if is_default is True:
        if not m.is_active:
            raise HTTPException(status_code=400, detail="Cannot set inactive membership as default")
        _clear_other_defaults(db, target.id, keep_membership_id=m.id)
        m.is_default = True
        target.branch_id = br.id
    elif is_default is False:
        m.is_default = False

    if hasattr(m, "updated_at"):
        m.updated_at = datetime.utcnow()
    log_audit(
        db,
        user=actor,
        action="branch.staff.updated",
        entity_type="user_branch",
        entity_id=m.id,
        branch_id=br.id,
        old_value=old,
        new_value=membership_to_dict(m),
        request=request,
    )
    db.flush()
    return m


def remove_staff(
    db: Session,
    actor: User,
    branch_id: int,
    user_id: int,
    *,
    hard: bool = False,
    request: Optional[Request] = None,
) -> None:
    if not (
        has_permission(actor, Perm.BRANCH_STAFF_REMOVE)
        or has_permission(actor, Perm.BRANCH_STAFF_ASSIGN)
        or has_permission(actor, Perm.MANAGE_BRANCHES)
        or has_permission(actor, Perm.MANAGE_USERS)
    ):
        raise HTTPException(status_code=403, detail="Permission denied: branch.staff.remove")

    br = get_tenant_branch(db, actor.tenant_id, branch_id)
    target = _require_tenant_user(db, actor.tenant_id, user_id)
    m = (
        db.query(UserBranch)
        .filter(UserBranch.user_id == target.id, UserBranch.branch_id == br.id)
        .first()
    )
    if m is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    # Prevent owner from removing their last admin path carelessly
    if is_admin_level(target) and target.id == actor.id:
        other = (
            db.query(UserBranch)
            .filter(
                UserBranch.user_id == target.id,
                UserBranch.is_active.is_(True),
                UserBranch.branch_id != br.id,
            )
            .count()
        )
        # Admins have implicit access; allow deactivate but log warning in audit
        log_audit(
            db,
            user=actor,
            action="branch.staff.self_remove_attempt",
            entity_type="user_branch",
            entity_id=m.id,
            branch_id=br.id,
            new_value={"other_memberships": other, "implicit_admin_access": True},
            request=request,
        )

    if hard:
        db.delete(m)
    else:
        m.is_active = False
        m.is_default = False
        if hasattr(m, "updated_at"):
            m.updated_at = datetime.utcnow()

    if target.branch_id == br.id:
        # Fall back to another active default/membership or clear
        alt = (
            db.query(UserBranch)
            .filter(
                UserBranch.user_id == target.id,
                UserBranch.is_active.is_(True),
                UserBranch.branch_id != br.id,
            )
            .order_by(UserBranch.is_default.desc(), UserBranch.id.asc())
            .first()
        )
        target.branch_id = alt.branch_id if alt else None

    log_audit(
        db,
        user=actor,
        action="branch.staff.removed",
        entity_type="user_branch",
        entity_id=m.id if not hard else None,
        branch_id=br.id,
        new_value={"user_id": target.id, "hard": hard},
        request=request,
    )
    db.flush()


def list_branch_staff(db: Session, actor: User, branch_id: int) -> List[Dict[str, Any]]:
    if not (
        has_permission(actor, Perm.BRANCH_VIEW)
        or has_permission(actor, Perm.BRANCH_STAFF_ASSIGN)
        or has_permission(actor, Perm.MANAGE_BRANCHES)
        or is_admin_level(actor)
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    br = get_tenant_branch(db, actor.tenant_id, branch_id)
    rows = (
        db.query(UserBranch, User)
        .join(User, User.id == UserBranch.user_id)
        .filter(UserBranch.branch_id == br.id)
        .order_by(UserBranch.is_active.desc(), User.username.asc())
        .all()
    )
    return [membership_to_dict(m, u) for m, u in rows]


def list_user_branches(db: Session, actor: User, user_id: int) -> List[Dict[str, Any]]:
    target = _require_tenant_user(db, actor.tenant_id, user_id)
    if not (
        is_admin_level(actor)
        or actor.id == target.id
        or has_permission(actor, Perm.BRANCH_STAFF_ASSIGN)
        or has_permission(actor, Perm.MANAGE_USERS)
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    rows = (
        db.query(UserBranch, Branch)
        .join(Branch, Branch.id == UserBranch.branch_id)
        .filter(UserBranch.user_id == target.id)
        .order_by(UserBranch.is_default.desc(), Branch.name.asc())
        .all()
    )
    out = []
    for m, br in rows:
        d = membership_to_dict(m)
        d["branch"] = active_branch_summary(br)
        out.append(d)
    return out


def switch_branch(
    db: Session,
    user: User,
    *,
    branch_id: Optional[int] = None,
    scope: str = SCOPE_BRANCH,
    request: Optional[Request] = None,
) -> Tuple[Optional[Branch], str]:
    """Validate and apply active branch switch. Returns (branch|None, scope)."""
    from .branch_context import user_has_branch_access

    if not has_permission(user, Perm.BRANCH_SWITCH) and not is_admin_level(user):
        # Cashiers have BRANCH_SWITCH; admins always can
        if not has_permission(user, Perm.BRANCH_VIEW):
            raise HTTPException(status_code=403, detail="Permission denied: branch.switch")

    scope_n = (scope or SCOPE_BRANCH).strip().lower()
    if scope_n == SCOPE_ALL:
        if not (
            has_permission(user, Perm.BRANCH_ANALYTICS_CONSOLIDATED)
            or is_admin_level(user)
        ):
            log_audit(
                db,
                user=user,
                action="branch.switch_denied",
                entity_type="branch",
                new_value={"scope": SCOPE_ALL, "reason": "no_consolidated_permission"},
                request=request,
            )
            raise HTTPException(
                status_code=403,
                detail="Consolidated mode requires branch.analytics.consolidated",
            )
        log_audit(
            db,
            user=user,
            action="branch.switched",
            entity_type="branch",
            new_value={"scope": SCOPE_ALL},
            request=request,
        )
        db.flush()
        return None, SCOPE_ALL

    if branch_id is None:
        raise HTTPException(status_code=400, detail="branchId is required when scope is branch")

    try:
        br = get_tenant_branch(db, user.tenant_id, int(branch_id))
    except HTTPException as e:
        log_audit(
            db,
            user=user,
            action="branch.switch_denied",
            entity_type="branch",
            entity_id=int(branch_id),
            new_value={"reason": "not_found_or_cross_tenant"},
            request=request,
        )
        raise e

    if not br.is_active:
        log_audit(
            db,
            user=user,
            action="branch.switch_denied",
            entity_type="branch",
            entity_id=br.id,
            new_value={"reason": "inactive"},
            request=request,
        )
        raise HTTPException(status_code=400, detail="Cannot switch into an inactive branch")

    if not user_has_branch_access(db, user, br.id):
        log_audit(
            db,
            user=user,
            action="branch.switch_denied",
            entity_type="branch",
            entity_id=br.id,
            new_value={"reason": "no_access"},
            request=request,
        )
        raise HTTPException(status_code=403, detail="No access to this branch")

    from .inventory_service import assert_can_switch_with_open_shift

    assert_can_switch_with_open_shift(db, user, br.id)

    # Persist legacy default for non-consolidated operation
    user.branch_id = br.id
    # Mark membership default if present
    m = (
        db.query(UserBranch)
        .filter(
            UserBranch.user_id == user.id,
            UserBranch.branch_id == br.id,
            UserBranch.is_active.is_(True),
        )
        .first()
    )
    if m is not None:
        _clear_other_defaults(db, user.id, keep_membership_id=m.id)
        m.is_default = True
        if hasattr(m, "updated_at"):
            m.updated_at = datetime.utcnow()

    log_audit(
        db,
        user=user,
        action="branch.switched",
        entity_type="branch",
        entity_id=br.id,
        branch_id=br.id,
        new_value={"scope": SCOPE_BRANCH, "branch_id": br.id},
        request=request,
    )
    logger.info(
        "branch_switch user_id=%s tenant_id=%s branch_id=%s",
        user.id,
        user.tenant_id,
        br.id,
    )
    db.flush()
    return br, SCOPE_BRANCH


def build_auth_branch_payload(
    db: Session,
    user: User,
    *,
    token_branch_id: Optional[int] = None,
    token_scope: Optional[str] = None,
) -> Dict[str, Any]:
    """Payload for /auth/me and login — no stock/analytics."""
    from .branch_context import resolve_branch_context

    scope = (token_scope or SCOPE_BRANCH).strip().lower()
    if scope == SCOPE_ALL and (
        has_permission(user, Perm.BRANCH_ANALYTICS_CONSOLIDATED) or is_admin_level(user)
    ):
        branches = list_branches_for_user(db, user, include_inactive=False)
        return {
            "activeBranch": None,
            "availableBranches": [active_branch_summary(b) for b in branches],
            "branchScope": SCOPE_ALL,
        }

    # Prefer validated token branch when present
    header = str(token_branch_id) if token_branch_id is not None else None
    try:
        ctx = resolve_branch_context(
            db,
            user,
            header_branch_id=header,
            token_branch_id=token_branch_id,
            token_scope=scope,
            require_branch=False,
        )
    except HTTPException:
        # Stale token branch revoked — fall back without explicit header
        ctx = resolve_branch_context(db, user, require_branch=False)

    branches = list_branches_for_user(db, user, include_inactive=False)
    return {
        "activeBranch": active_branch_summary(ctx.branch),
        "availableBranches": [active_branch_summary(b) for b in branches],
        "branchScope": SCOPE_BRANCH,
    }


def stock_row_count_for_branch(db: Session, branch_id: int) -> int:
    return (
        db.query(BranchProductStock)
        .filter(BranchProductStock.branch_id == branch_id)
        .count()
    )
