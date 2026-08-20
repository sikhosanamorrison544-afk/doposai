"""Central post-login landing paths by role (server + docs for UI parity)."""
from __future__ import annotations

from typing import Optional

from .models import User
from .permissions import Perm, can_access_pos, has_permission, normalize_role


LANDING_OVERVIEW = "/overview"
LANDING_POS = "/"


def post_login_path(user: Optional[User] = None, role: Optional[str] = None) -> str:
    """
    Administrator / owner → Business Overview Dashboard
    Users with sales permission (cashier, supervisor) → POS ``/``
    """
    if user is not None:
        r = normalize_role(user.role)
        if r == "admin":
            return LANDING_OVERVIEW
        if can_access_pos(user):
            return LANDING_POS
        if has_permission(user, Perm.VIEW_REPORTS):
            return LANDING_OVERVIEW
        return LANDING_POS

    r = normalize_role(role or "")
    if r == "admin":
        return LANDING_OVERVIEW
    return LANDING_POS


def can_access_overview(user: User) -> bool:
    """Overview requires reporting permission (admin + supervisor)."""
    return has_permission(user, Perm.VIEW_REPORTS)
