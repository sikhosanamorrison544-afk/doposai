"""
Section 13 — Branch management, staff membership, and switching APIs.

Prefix: /api/branches
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import auth
from .branch_service import (
    SCOPE_ALL,
    SCOPE_BRANCH,
    activate_branch,
    assign_staff,
    branch_to_dict,
    build_auth_branch_payload,
    count_active_staff,
    create_branch,
    deactivate_branch,
    get_tenant_branch,
    list_all_tenant_branches,
    list_branch_staff,
    list_branches_for_user,
    list_user_branches,
    membership_to_dict,
    remove_staff,
    stock_row_count_for_branch,
    switch_branch,
    update_branch,
    update_staff_membership,
)
from .database import get_db
from .models import User
from .permissions import Perm, dep_perm, has_permission, is_admin_level

router = APIRouter(prefix="/api/branches", tags=["branches"])


class BranchCreateIn(BaseModel):
    name: str
    code: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    manager_user_id: Optional[int] = None
    is_main: bool = False
    is_default: Optional[bool] = None  # alias


class BranchUpdateIn(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    manager_user_id: Optional[int] = None
    is_main: Optional[bool] = None
    is_default: Optional[bool] = None


class StaffAssignIn(BaseModel):
    user_id: int
    role: str = "cashier"
    is_default: bool = False


class StaffUpdateIn(BaseModel):
    role: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class BranchSwitchIn(BaseModel):
    model_config = {"populate_by_name": True}

    branchId: Optional[int] = Field(None, alias="branchId")
    branch_id: Optional[int] = None
    scope: str = SCOPE_BRANCH


def _issue_branch_token(user: User, branch_id: Optional[int], scope: str) -> str:
    payload: Dict[str, Any] = {"sub": user.username, "role": user.role, "bscope": scope}
    if user.tenant_id is not None:
        payload["tid"] = user.tenant_id
    if scope == SCOPE_BRANCH and branch_id is not None:
        payload["bid"] = int(branch_id)
    return auth.create_access_token(data=payload)


@router.get("")
def api_list_branches(
    include_inactive: bool = Query(False),
    manage: bool = Query(False, description="Admin list of all tenant branches"),
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_active_user),
):
    """List branches the caller may access (or full tenant list for managers)."""
    if manage:
        if not (
            is_admin_level(user)
            or has_permission(user, Perm.MANAGE_BRANCHES)
            or has_permission(user, Perm.BRANCH_VIEW)
        ):
            raise HTTPException(status_code=403, detail="Permission denied")
        rows = list_all_tenant_branches(db, user, include_inactive=include_inactive)
    else:
        rows = list_branches_for_user(db, user, include_inactive=include_inactive)
    out = []
    for br in rows:
        d = branch_to_dict(br, staff_count=count_active_staff(db, br.id))
        out.append(d)
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
def api_create_branch(
    body: BranchCreateIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_CREATE)),
):
    is_main = bool(body.is_main) or bool(body.is_default)
    br = create_branch(
        db,
        user,
        name=body.name,
        code=body.code,
        address=body.address,
        phone=body.phone,
        email=body.email,
        manager_user_id=body.manager_user_id,
        is_main=is_main,
        request=request,
    )
    # Do not copy Product.stock_qty into BranchProductStock (Section 13 / 14).
    db.commit()
    db.refresh(br)
    d = branch_to_dict(br, staff_count=0)
    d["inventory_rows"] = stock_row_count_for_branch(db, br.id)
    return d


@router.get("/me/context")
def api_branch_context(
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_active_user),
):
    """Active branch + available branches (same shape as auth/me branch fields)."""
    return build_auth_branch_payload(
        db,
        user,
        token_branch_id=getattr(user, "_token_branch_id", None),
        token_scope=getattr(user, "_token_branch_scope", None),
    )


@router.post("/switch")
def api_switch_branch(
    body: BranchSwitchIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_active_user),
):
    bid = body.branchId if body.branchId is not None else body.branch_id
    br, scope = switch_branch(
        db, user, branch_id=bid, scope=body.scope or SCOPE_BRANCH, request=request
    )
    db.commit()
    token = _issue_branch_token(user, br.id if br else None, scope)
    resp = {
        "activeBranch": (
            {"id": br.id, "name": br.name, "code": br.code} if br is not None else None
        ),
        "scope": scope,
        "access_token": token,
        "token_type": "bearer",
    }
    from fastapi.responses import JSONResponse

    response = JSONResponse(content=resp)
    auth.attach_access_cookie(response, token)
    return response


@router.get("/{branch_id}")
def api_get_branch(
    branch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_active_user),
):
    from .branch_context import user_has_branch_access

    br = get_tenant_branch(db, user.tenant_id, branch_id)
    if not user_has_branch_access(db, user, br.id) and not (
        has_permission(user, Perm.BRANCH_VIEW) or has_permission(user, Perm.MANAGE_BRANCHES)
    ):
        raise HTTPException(status_code=403, detail="No access to this branch")
    return branch_to_dict(br, staff_count=count_active_staff(db, br.id))


@router.patch("/{branch_id}")
def api_update_branch(
    branch_id: int,
    body: BranchUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_UPDATE)),
):
    is_main = body.is_main if body.is_main is not None else body.is_default
    data = body.model_dump(exclude_unset=True)
    # manager_user_id may be explicitly null
    kwargs: Dict[str, Any] = {}
    for k in ("name", "code", "address", "phone", "email"):
        if k in data:
            kwargs[k] = data[k]
    if "manager_user_id" in data:
        kwargs["manager_user_id"] = data["manager_user_id"]
    br = update_branch(
        db,
        user,
        branch_id,
        is_main=is_main,
        request=request,
        **kwargs,
    )
    db.commit()
    db.refresh(br)
    return branch_to_dict(br, staff_count=count_active_staff(db, br.id))


@router.post("/{branch_id}/activate")
def api_activate_branch(
    branch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_UPDATE)),
):
    br = activate_branch(db, user, branch_id, request=request)
    db.commit()
    db.refresh(br)
    return branch_to_dict(br)


@router.post("/{branch_id}/deactivate")
def api_deactivate_branch(
    branch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_DEACTIVATE)),
):
    br = deactivate_branch(db, user, branch_id, request=request)
    db.commit()
    db.refresh(br)
    return branch_to_dict(br)


@router.get("/{branch_id}/staff")
def api_list_staff(
    branch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_active_user),
):
    return list_branch_staff(db, user, branch_id)


@router.post("/{branch_id}/staff", status_code=status.HTTP_201_CREATED)
def api_assign_staff(
    branch_id: int,
    body: StaffAssignIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_STAFF_ASSIGN)),
):
    m = assign_staff(
        db,
        user,
        branch_id,
        user_id=body.user_id,
        role=body.role,
        is_default=body.is_default,
        request=request,
    )
    db.commit()
    db.refresh(m)
    return membership_to_dict(m)


@router.patch("/{branch_id}/staff/{user_id}")
def api_update_staff(
    branch_id: int,
    user_id: int,
    body: StaffUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_STAFF_ASSIGN)),
):
    m = update_staff_membership(
        db,
        user,
        branch_id,
        user_id,
        role=body.role,
        is_default=body.is_default,
        is_active=body.is_active,
        request=request,
    )
    db.commit()
    db.refresh(m)
    return membership_to_dict(m)


@router.delete("/{branch_id}/staff/{user_id}")
def api_remove_staff(
    branch_id: int,
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_STAFF_REMOVE)),
):
    remove_staff(db, user, branch_id, user_id, hard=False, request=request)
    db.commit()
    return {"ok": True}


# User-centric membership list lives under /api/users/... — registered in main or here with different prefix
users_router = APIRouter(prefix="/api/users", tags=["branches"])


@users_router.get("/{user_id}/branches")
def api_user_branches(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_active_user),
):
    return list_user_branches(db, user, user_id)
