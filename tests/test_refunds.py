"""Tests for refund service helpers."""
from app.models import User
from app.permissions import Perm, has_permission


def _user(role: str) -> User:
    return User(username=f"u_{role}", role=role, password_hash="x", is_active=True)


def test_cashier_can_request_refunds():
    assert has_permission(_user("cashier"), Perm.REQUEST_REFUNDS)
    assert not has_permission(_user("cashier"), Perm.APPROVE_REFUNDS)
    assert not has_permission(_user("cashier"), Perm.VIEW_REFUNDS)


def test_supervisor_can_approve_refunds():
    u = _user("supervisor")
    assert has_permission(u, Perm.REQUEST_REFUNDS)
    assert has_permission(u, Perm.VIEW_REFUNDS)
    assert has_permission(u, Perm.APPROVE_REFUNDS)


def test_admin_has_all_refund_permissions():
    u = _user("admin")
    assert has_permission(u, Perm.REQUEST_REFUNDS)
    assert has_permission(u, Perm.VIEW_REFUNDS)
    assert has_permission(u, Perm.APPROVE_REFUNDS)
