"""Tests for role-based permissions."""
from app.models import User
from app.permissions import (
    Perm,
    has_permission,
    is_admin_level,
    is_supervisor_or_above,
    permissions_as_strings,
    user_permissions,
)


def _user(role: str) -> User:
    return User(username=f"u_{role}", role=role, password_hash="x", is_active=True)


def test_admin_has_management_permissions_without_sales():
    perms = user_permissions(_user("admin"))
    assert Perm.MANAGE_USERS in perms
    assert Perm.MANAGE_BRANCHES in perms
    assert Perm.PROCESS_WITHDRAWALS in perms
    assert Perm.SALES not in perms
    assert len(perms) == len(Perm) - 1


def test_supervisor_operational_permissions():
    user = _user("supervisor")
    assert has_permission(user, Perm.SALES)
    assert has_permission(user, Perm.VIEW_INVENTORY)
    assert has_permission(user, Perm.PROCESS_WITHDRAWALS)
    assert has_permission(user, Perm.APPROVE_REFUNDS)
    assert has_permission(user, Perm.REQUEST_REFUNDS)
    assert has_permission(user, Perm.VIEW_REFUNDS)
    assert has_permission(user, Perm.MANAGE_PENDING_COLLECTION)
    assert has_permission(user, Perm.MANAGE_SHIFTS)
    assert has_permission(user, Perm.VIEW_REPORTS)
    assert not has_permission(user, Perm.MANAGE_USERS)
    assert not has_permission(user, Perm.MANAGE_SETTINGS)
    assert not has_permission(user, Perm.MANAGE_SUPPLIERS)
    assert not has_permission(user, Perm.MANAGE_BRANCHES)


def test_cashier_pos_only():
    user = _user("cashier")
    assert has_permission(user, Perm.SALES)
    assert has_permission(user, Perm.VIEW_INVENTORY)
    assert has_permission(user, Perm.REQUEST_REFUNDS)
    assert not has_permission(user, Perm.PROCESS_WITHDRAWALS)
    assert not has_permission(user, Perm.APPROVE_REFUNDS)
    assert not has_permission(user, Perm.VIEW_REFUNDS)


def test_role_helpers():
    assert is_admin_level(_user("admin"))
    assert is_admin_level(_user("owner"))
    assert not is_admin_level(_user("supervisor"))
    assert is_supervisor_or_above(_user("supervisor"))
    assert is_supervisor_or_above(_user("admin"))
    assert not is_supervisor_or_above(_user("cashier"))


def test_permissions_as_strings_sorted():
    names = permissions_as_strings(_user("cashier"))
    assert names == sorted(names)
    assert "sales" in names
    assert "process_withdrawals" not in names


def test_can_access_pos_requires_sales():
    from app.permissions import can_access_pos

    assert can_access_pos(_user("cashier")) is True
    assert can_access_pos(_user("supervisor")) is True
    assert can_access_pos(_user("admin")) is False
    assert can_access_pos(_user("owner")) is False
