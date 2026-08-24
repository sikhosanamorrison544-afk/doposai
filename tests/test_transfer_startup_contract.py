"""
Section 15 startup contract tests.

Guards the production boot contract:

- every ``Perm.*`` referenced by ``app/transfer_routes.py`` exists in the
  canonical ``Perm`` enum. A missing member raises ``AttributeError`` while
  ``app.main`` is imported, killing Gunicorn with exit code 3 (this happened
  in production when ``BRANCH_TRANSFER_CREATE`` was committed in the routes
  but omitted from ``app/permissions.py``);
- ``app.main`` imports cleanly and the 14 ``/api/transfers`` routes are
  registered;
- the committed permission definitions grant the expected roles:
  owner/admin all transfer permissions, supervisor the operational set,
  cashier none.
"""
from __future__ import annotations

import ast
from pathlib import Path

from app.models import User

ROUTES_FILE = Path(__file__).resolve().parents[1] / "app" / "transfer_routes.py"

# The exact set of transfer permissions referenced by transfer_routes.py.
EXPECTED_TRANSFER_PERMS = {
    "BRANCH_TRANSFER_VIEW",
    "BRANCH_TRANSFER_CREATE",
    "BRANCH_TRANSFER_REQUEST",
    "BRANCH_TRANSFER_APPROVE",
    "BRANCH_TRANSFER_REJECT",
    "BRANCH_TRANSFER_CANCEL",
    "BRANCH_TRANSFER_DISPATCH",
    "BRANCH_TRANSFER_RECEIVE",
}

# (method, path) pairs — all 14 routes exposed under the /api/transfers prefix.
EXPECTED_TRANSFER_ROUTES = {
    ("GET", "/api/transfers"),
    ("POST", "/api/transfers"),
    ("GET", "/api/transfers/{transfer_id}"),
    ("PATCH", "/api/transfers/{transfer_id}"),
    ("DELETE", "/api/transfers/{transfer_id}"),
    ("POST", "/api/transfers/{transfer_id}/items"),
    ("PUT", "/api/transfers/{transfer_id}/items/{item_id}"),
    ("DELETE", "/api/transfers/{transfer_id}/items/{item_id}"),
    ("POST", "/api/transfers/{transfer_id}/request"),
    ("POST", "/api/transfers/{transfer_id}/approve"),
    ("POST", "/api/transfers/{transfer_id}/reject"),
    ("POST", "/api/transfers/{transfer_id}/cancel"),
    ("POST", "/api/transfers/{transfer_id}/dispatch"),
    ("POST", "/api/transfers/{transfer_id}/receive"),
}


# --- route -> permission enum contract -------------------------------------


def _route_referenced_perms() -> set:
    """Extract ``Perm.<NAME>`` attribute references from transfer_routes.py."""
    tree = ast.parse(ROUTES_FILE.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "Perm"
        ):
            found.add(node.attr)
    return found


def test_every_route_reference_is_an_enum_member():
    """Fail if any Perm.* in the routes is not defined in the canonical enum."""
    from app.permissions import Perm

    referenced = _route_referenced_perms()
    assert referenced == EXPECTED_TRANSFER_PERMS, (
        f"route permission set drifted: {sorted(referenced)}"
    )
    missing = referenced - set(Perm.__members__)
    assert not missing, (
        f"transfer_routes.py references undefined Perm members: {sorted(missing)}. "
        "This makes app.main un-importable and breaks production boot."
    )


def test_transfer_permission_names_are_importable():
    from app.permissions import Perm

    for name in EXPECTED_TRANSFER_PERMS:
        assert getattr(Perm, name, None) is not None, f"missing Perm.{name}"
        assert getattr(Perm, name).value.startswith("branch.transfer."), (
            f"Perm.{name} uses an unexpected value format"
        )


def test_app_main_imports_cleanly():
    import app.main  # noqa: F401


# --- route registration contract -------------------------------------------


def test_all_14_transfer_routes_are_registered():
    from app.main import app

    pairs = {
        (method, route.path)
        for route in app.routes
        if hasattr(route, "methods")
        for method in route.methods
        if route.path == "/api/transfers" or route.path.startswith("/api/transfers/")
    }
    assert pairs == EXPECTED_TRANSFER_ROUTES
    assert len(pairs) == 14


# --- committed role grant contract -----------------------------------------


def _user(role: str) -> User:
    return User(username=f"contract_{role}", role=role, password_hash="x", is_active=True)


def test_owner_and_admin_have_all_transfer_permissions():
    from app.permissions import Perm, user_permissions

    for role in ("owner", "admin"):
        perms = user_permissions(_user(role))
        for name in EXPECTED_TRANSFER_PERMS:
            assert getattr(Perm, name) in perms, f"{role} missing Perm.{name}"


def test_supervisor_has_intended_operational_transfer_permissions():
    from app.permissions import Perm, user_permissions

    perms = user_permissions(_user("supervisor"))
    for name in EXPECTED_TRANSFER_PERMS:
        assert getattr(Perm, name) in perms, f"supervisor missing Perm.{name}"


def test_cashier_has_no_approval_dispatch_receive():
    from app.permissions import Perm, user_permissions

    perms = user_permissions(_user("cashier"))
    for name in EXPECTED_TRANSFER_PERMS:
        assert getattr(Perm, name) not in perms, f"cashier should not have Perm.{name}"
