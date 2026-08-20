"""Platform-owner allowlist (`is_platform_owner_user`).

Usernames are NOT globally unique across tenants. Email gating is preferred.
Allowlists are read live from env via config getters so suite import order
cannot freeze empty frozensets into platform_routes.
"""
from __future__ import annotations

import pytest

from app.models import User
from app import platform_routes as pr


@pytest.fixture(autouse=True)
def _platform_owner_allowlists(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_USERNAMES", "owner_user")
    monkeypatch.setenv("PLATFORM_OWNER_EMAILS", "owner@example.com")
    yield


def _make_user(*, username, email, role="admin", is_active=True) -> User:
    u = User()
    u.username = username
    u.email = email
    u.role = role
    u.is_active = is_active
    return u


def test_email_match_grants_access():
    u = _make_user(username="some-random-name", email="owner@example.com")
    assert pr.is_platform_owner_user(u) is True


def test_email_match_is_case_insensitive():
    u = _make_user(username="x", email="Owner@Example.COM")
    assert pr.is_platform_owner_user(u) is True


def test_username_match_grants_access():
    u = _make_user(username="owner_user", email="not-on-list@example.com")
    assert pr.is_platform_owner_user(u) is True


def test_regular_tenant_admin_is_denied_even_if_username_is_admin():
    u = _make_user(username="admin", email="cust@somebiz.com")
    assert pr.is_platform_owner_user(u) is False


def test_non_admin_role_denied_even_if_email_matches():
    u = _make_user(username="x", email="owner@example.com", role="cashier")
    assert pr.is_platform_owner_user(u) is False


def test_inactive_user_denied_even_if_email_matches():
    u = _make_user(username="x", email="owner@example.com", is_active=False)
    assert pr.is_platform_owner_user(u) is False


def test_empty_email_does_not_falsely_match_empty_allowlist_entry():
    u = _make_user(username="not-owner", email="")
    assert pr.is_platform_owner_user(u) is False


def test_user_missing_email_attr_is_denied_cleanly():
    u = User()
    u.username = "x"
    u.email = None
    u.role = "admin"
    u.is_active = True
    assert pr.is_platform_owner_user(u) is False


def test_is_platform_owner_tenant_by_tenant_email():
    """Tenant registration email on allowlist → complimentary Pro tenant."""
    from app.quotation_models import Tenant

    t = Tenant()
    t.id = 1
    t.tenant_uid = "test-uid"
    t.name = "My Test Shop"
    t.email = "owner@example.com"

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return []

    class FakeDb:
        def query(self, model):
            return FakeQuery()

    assert pr.is_platform_owner_tenant(FakeDb(), t) is True


def test_empty_allowlist_denies_everyone(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_USERNAMES", "")
    monkeypatch.setenv("PLATFORM_OWNER_EMAILS", "")
    u = _make_user(username="owner_user", email="owner@example.com")
    assert pr.is_platform_owner_user(u) is False
