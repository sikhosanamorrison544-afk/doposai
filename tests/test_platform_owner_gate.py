"""Unit tests for the platform-owner allowlist (`is_platform_owner_user`).

The key invariant we're protecting here: usernames are NOT globally
unique across tenants in this SaaS deployment (every tenant's primary
admin uses ``admin`` by default). The introduction of email-based
gating exists specifically so the platform banner does NOT leak to
other tenants when the operator forgets to make the username gate
restrictive.
"""
from __future__ import annotations

import os
import sys

# Configure both allowlists BEFORE importing the module under test, since
# the env vars are parsed once at import time.
os.environ.setdefault("PLATFORM_OWNER_USERNAMES", "owner_user")
os.environ.setdefault("PLATFORM_OWNER_EMAILS", "owner@example.com")

# Reload config + platform_routes if they've been imported by an earlier
# test in the same process — otherwise the frozensets won't reflect the
# values we just set.
for _mod in ("app.config", "app.platform_routes"):
    if _mod in sys.modules:
        del sys.modules[_mod]

from app import platform_routes as pr  # noqa: E402
from app.models import User  # noqa: E402


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
    # This is the core bug we're fixing: every tenant signs up with
    # username='admin', so an admin-username gate must NOT grant them
    # platform-owner access just because their email isn't on the list.
    u = _make_user(username="admin", email="cust@somebiz.com")
    assert pr.is_platform_owner_user(u) is False


def test_non_admin_role_denied_even_if_email_matches():
    u = _make_user(username="x", email="owner@example.com", role="cashier")
    assert pr.is_platform_owner_user(u) is False


def test_inactive_user_denied_even_if_email_matches():
    u = _make_user(username="x", email="owner@example.com", is_active=False)
    assert pr.is_platform_owner_user(u) is False


def test_empty_email_does_not_falsely_match_empty_allowlist_entry():
    # Defensive: if a user record has email='' it must not match an
    # empty string in the allowlist (the parser already strips empties,
    # but we double-check).
    u = _make_user(username="not-owner", email="")
    assert pr.is_platform_owner_user(u) is False


def test_user_missing_email_attr_is_denied_cleanly():
    # Some code paths may construct users without an email attribute
    # set; we should not crash.
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
