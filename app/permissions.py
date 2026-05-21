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
    VIEW_REPORTS = "view_reports"
    VIEW_AUDIT = "view_audit"
    MANAGE_USERS = "manage_users"
    MANAGE_SETTINGS = "manage_settings"
    MANAGE_ACCOUNTING = "manage_accounting"
    EXPORT_DATA = "export_data"
    PROCESS_WITHDRAWALS = "process_withdrawals"
    VIEW_WITHDRAWALS = "view_withdrawals"
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
    "owner": set(Perm),
    "admin": set(Perm),
    "supervisor": {
        Perm.SALES,
        Perm.VIEW_INVENTORY,
        Perm.PROCESS_WITHDRAWALS,
        Perm.VIEW_WITHDRAWALS,
        Perm.REQUEST_REFUNDS,
        Perm.VIEW_REFUNDS,
        Perm.APPROVE_REFUNDS,
        Perm.MANAGE_PENDING_COLLECTION,
        Perm.VIEW_REPORTS,
        Perm.MANAGE_SHIFTS,
    },
    "cashier": {
        Perm.SALES,
        Perm.VIEW_INVENTORY,
        Perm.REQUEST_REFUNDS,
    },
}

ROLE_DESCRIPTIONS: dict[str, str] = {
    "admin": "Full access — inventory, settings, users, billing, enterprise, and all reports.",
    "supervisor": "Operational lead — process withdrawals, approve refunds, mark pending collections, and manage shifts.",
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
