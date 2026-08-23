"""
Role-based permissions for POS and enterprise modules.

Roles: admin (tenant owner), supervisor, cashier.
Platform owner is separate (platform_routes).
"""
from __future__ import annotations

from enum import Enum
from typing import List, Set

from fastapi import Depends, HTTPException, status

from . import auth
from .models import User


class Perm(str, Enum):
    SALES = "sales"
    VIEW_INVENTORY = "view_inventory"
    MANAGE_INVENTORY = "manage_inventory"
    APPROVE_ADJUSTMENTS = "approve_adjustments"
    MANAGE_SUPPLIERS = "manage_suppliers"
    MANAGE_PURCHASING = "manage_purchasing"
    RECEIVE_STOCK = "receive_stock"
    MANAGE_BRANCHES = "manage_branches"
    MANAGE_TRANSFERS = "manage_transfers"
    # Section 12 — granular branch permissions (admin inherits all via role set).
    BRANCH_CREATE = "branch.create"
    BRANCH_VIEW = "branch.view"
    BRANCH_UPDATE = "branch.update"
    BRANCH_DEACTIVATE = "branch.deactivate"
    BRANCH_SWITCH = "branch.switch"
    BRANCH_STAFF_ASSIGN = "branch.staff.assign"
    BRANCH_STAFF_REMOVE = "branch.staff.remove"
    BRANCH_STOCK_VIEW = "branch.stock.view"
    BRANCH_STOCK_ADJUST = "branch.stock.adjust"
    BRANCH_TRANSFER_REQUEST = "branch.transfer.request"
    BRANCH_TRANSFER_APPROVE = "branch.transfer.approve"
    BRANCH_TRANSFER_DISPATCH = "branch.transfer.dispatch"
    BRANCH_TRANSFER_RECEIVE = "branch.transfer.receive"
    BRANCH_TRANSFER_REJECT = "branch.transfer.reject"
    BRANCH_TRANSFER_CANCEL = "branch.transfer.cancel"
    BRANCH_TRANSFER_VIEW = "branch.transfer.view"
    BRANCH_ANALYTICS_VIEW = "branch.analytics.view"
    BRANCH_ANALYTICS_CONSOLIDATED = "branch.analytics.consolidated"
    VIEW_REPORTS = "view_reports"
    VIEW_AUDIT = "view_audit"
    MANAGE_USERS = "manage_users"
    MANAGE_SETTINGS = "manage_settings"
    MANAGE_ACCOUNTING = "manage_accounting"
    EXPORT_DATA = "export_data"
    PROCESS_WITHDRAWALS = "process_withdrawals"
    VIEW_WITHDRAWALS = "view_withdrawals"
    VIEW_EXPENSES = "view_expenses"
    MANAGE_EXPENSES = "manage_expenses"
    APPROVE_REFUNDS = "approve_refunds"
    REQUEST_REFUNDS = "request_refunds"
    VIEW_REFUNDS = "view_refunds"
    MANAGE_PENDING_COLLECTION = "manage_pending_collection"
    MANAGE_SHIFTS = "manage_shifts"


OWNER_ROLES = frozenset({"admin", "owner"})
ADMIN_ROLES = OWNER_ROLES
SUPERVISOR_ROLES = frozenset({"supervisor"})
CASHIER_ROLES = frozenset({"cashier"})

_ROLE_PERMS: dict[str, Set[Perm]] = {
    # Admin/owner manage the business but do not sell on the POS by default.
    "owner": {p for p in Perm if p != Perm.SALES},
    "admin": {p for p in Perm if p != Perm.SALES},
    "supervisor": {
        Perm.SALES,
        Perm.VIEW_INVENTORY,
        Perm.PROCESS_WITHDRAWALS,
        Perm.VIEW_WITHDRAWALS,
        Perm.VIEW_EXPENSES,
        Perm.MANAGE_EXPENSES,
        Perm.REQUEST_REFUNDS,
        Perm.VIEW_REFUNDS,
        Perm.APPROVE_REFUNDS,
        Perm.MANAGE_PENDING_COLLECTION,
        Perm.VIEW_REPORTS,
        Perm.MANAGE_SHIFTS,
        Perm.BRANCH_VIEW,
        Perm.BRANCH_SWITCH,
        Perm.BRANCH_STOCK_VIEW,
        Perm.BRANCH_STOCK_ADJUST,
        Perm.BRANCH_TRANSFER_REQUEST,
        Perm.BRANCH_TRANSFER_APPROVE,
        Perm.BRANCH_TRANSFER_DISPATCH,
        Perm.BRANCH_TRANSFER_RECEIVE,
        Perm.BRANCH_TRANSFER_REJECT,
        Perm.BRANCH_TRANSFER_CANCEL,
        Perm.BRANCH_TRANSFER_VIEW,
        Perm.BRANCH_ANALYTICS_VIEW,
        Perm.MANAGE_TRANSFERS,
    },
    "cashier": {
        Perm.SALES,
        Perm.VIEW_INVENTORY,
        Perm.REQUEST_REFUNDS,
        Perm.BRANCH_VIEW,
        Perm.BRANCH_SWITCH,
        Perm.BRANCH_STOCK_VIEW,
    },
}

ROLE_DESCRIPTIONS: dict[str, str] = {
    "admin": "Full business access — inventory, settings, users, billing, enterprise, and reports. No POS selling.",
    "supervisor": "Operational lead — sell on POS, process withdrawals, approve refunds, pending collections, and shifts.",
    "cashier": "Point of sale only — ring up sales and view stock levels.",
}


def normalize_role(role: str) -> str:
    r = (role or "").strip().lower()
    if r == "owner":
        return "admin"
    return r


def user_permissions(user: User) -> Set[Perm]:
    role = normalize_role(user.role)
    return _ROLE_PERMS.get(role, set())


def permissions_as_strings(user: User) -> List[str]:
    return sorted(p.value for p in user_permissions(user))


def has_permission(user: User, perm: Perm) -> bool:
    return perm in user_permissions(user)


def can_access_pos(user: User) -> bool:
    """POS selling page requires explicit sales permission (not admin-by-default)."""
    return has_permission(user, Perm.SALES)


def require_permission(user: User, perm: Perm) -> None:
    if not has_permission(user, perm):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {perm.value}",
        )


def require_any_inventory(user: User) -> None:
    require_permission(
        user,
        Perm.MANAGE_INVENTORY
        if has_permission(user, Perm.MANAGE_INVENTORY)
        else Perm.VIEW_INVENTORY,
    )


def is_admin_level(user: User) -> bool:
    return normalize_role(user.role) in ADMIN_ROLES


def is_supervisor_or_above(user: User) -> bool:
    role = normalize_role(user.role)
    return role in ADMIN_ROLES or role in SUPERVISOR_ROLES


def require_admin_level(user: User) -> None:
    if not is_admin_level(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


def require_supervisor_or_above(user: User) -> None:
    if not is_supervisor_or_above(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Supervisor access required")


def dep_perm(perm: Perm):
    async def _checker(user: User = Depends(auth.get_current_active_user)) -> User:
        require_permission(user, perm)
        return user

    return _checker
