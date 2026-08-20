"""HTML page-level authorization for management shells (cookie session)."""
from __future__ import annotations

from typing import Optional, Sequence, Union
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from . import auth
from .landing import post_login_path
from .models import User
from .permissions import Perm, has_permission


def login_redirect(request: Request) -> RedirectResponse:
    """Unauthenticated visitors → POS login shell with return path."""
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(
        url=f"/?next={quote(next_path, safe='/?&=')}",
        status_code=303,
    )


def unauthorized_redirect(user: User) -> RedirectResponse:
    """Authenticated but missing permission → authorised landing page."""
    return RedirectResponse(url=post_login_path(user), status_code=303)


def gate_page(
    request: Request,
    db: Session,
    *,
    any_of: Sequence[Perm],
) -> Union[RedirectResponse, User]:
    """
    Enforce cookie auth + permission for management HTML pages.

    Returns the User when allowed, otherwise a RedirectResponse:
      * no cookie / invalid cookie → ``/?next=…``
      * missing permission → ``post_login_path(user)``
    """
    user = auth.user_from_access_cookie(request, db)
    if user is None:
        return login_redirect(request)
    if not any(has_permission(user, p) for p in any_of):
        return unauthorized_redirect(user)
    return user


def is_redirect(result: Union[RedirectResponse, User]) -> bool:
    return isinstance(result, RedirectResponse)
