"""
Role-based permissions for enterprise modules.

Roles: admin (tenant owner), supervisor, cashier.
Platform owner is separate (platform_routes).
"""
from __future__ import annotations

from enum import Enum
from typing import Set

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
        Perm.MANAGE_INVENTORY,
        Perm.MANAGE_SUPPLIERS,
        Perm.MANAGE_PURCHASING,
        Perm.RECEIVE_STOCK,
        Perm.VIEW_REPORTS,
        Perm.EXPORT_DATA,
    },
    "cashier": {
        Perm.SALES,
        Perm.VIEW_INVENTORY,
    },
}


def normalize_role(role: str) -> str:
    r = (role or "").strip().lower()
    if r == "owner":
        return "admin"
    return r


def user_permissions(user: User) -> Set[Perm]:
    role = normalize_role(user.role)
    return _ROLE_PERMS.get(role, set())


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


def require_admin_level(user: User) -> None:
    if not is_admin_level(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


def require_supervisor_or_above(user: User) -> None:
    role = normalize_role(user.role)
    if role not in ADMIN_ROLES and role not in SUPERVISOR_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Supervisor access required")


def dep_perm(perm: Perm):
    async def _checker(user: User = Depends(auth.get_current_active_user)) -> User:
        require_permission(user, perm)
        return user

    return _checker
