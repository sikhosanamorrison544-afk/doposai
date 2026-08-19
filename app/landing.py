"""Central post-login landing paths by role (server + docs for UI parity)."""
from __future__ import annotations

from typing import Optional

from .models import User
from .permissions import normalize_role


# Paths relative to site origin (leading slash).
LANDING_OVERVIEW = "/overview"
LANDING_POS = "/"


def post_login_path(user: Optional[User] = None, role: Optional[str] = None) -> str:
    """
    Resolve the first page after successful authentication.

    Administrator / owner → Business Overview Dashboard
    Cashier, supervisor, and others → main POS selling page
    """
    if user is not None:
        role = user.role
    r = normalize_role(role or "")
    if r == "admin":
        return LANDING_OVERVIEW
    return LANDING_POS


def can_access_overview(user: User) -> bool:
    """Overview requires reporting permission (admin + supervisor)."""
    from .permissions import Perm, has_permission

    return has_permission(user, Perm.VIEW_REPORTS)
