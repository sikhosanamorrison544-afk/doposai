from datetime import datetime, timedelta
import hashlib
import secrets
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import PWD_HASH_SCHEME
from .database import get_db
from .models import User
from .security_config import JWT_ALGORITHM, load_jwt_secret_from_env

# Single source of truth: validated at import from JWT_SECRET_KEY (no code fallback).
SECRET_KEY = load_jwt_secret_from_env()
ALGORITHM = JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = 8 * 60  # 8 hours
REFRESH_TOKEN_EXPIRE_DAYS = 30

# HttpOnly cookie so HTML routes (GET /) can enforce POS access without relying on JS alone.
POS_ACCESS_COOKIE = "pos_access_token"

pwd_context = CryptContext(schemes=[PWD_HASH_SCHEME], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": int(datetime.utcnow().timestamp())})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and verify an access JWT.

    Accepts only ALGORITHM (HS256). Requires exp. Raises JWTError on failure.
    """
    return jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM],
        options={"require_exp": True},
    )


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_opaque_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    # Case-insensitive username lookup
    return db.query(User).filter(func.lower(User.username) == func.lower(username)).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    if not email:
        return None
    return db.query(User).filter(func.lower(User.email) == func.lower(email.strip())).first()


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = get_user_by_username(db, username)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        tid_claim = payload.get("tid")
    except JWTError:
        raise credentials_exception
    user = get_user_by_username(db, username=username)
    if user is None or not user.is_active:
        raise credentials_exception
    if user.tenant_id is not None:
        if tid_claim is not None and int(tid_claim) != int(user.tenant_id):
            raise credentials_exception
    elif tid_claim is not None:
        raise credentials_exception
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    from .permissions import require_admin_level

    require_admin_level(current_user)
    return current_user


async def get_current_supervisor_or_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    from .permissions import require_supervisor_or_above

    require_supervisor_or_above(current_user)
    return current_user


def set_access_cookie(response: Response, access_token: str) -> None:
    """
    Set the HttpOnly POS access cookie used by HTML route guards.

    Attributes follow project defaults: HttpOnly, SameSite=Lax, path=/,
    max-age matching access-token lifetime. Secure is enabled in production
    (or when POS_COOKIE_SECURE=1). Optional POS_COOKIE_DOMAIN is applied when set.
    """
    import os

    from .config import APP_ENV

    secure_flag = os.environ.get("POS_COOKIE_SECURE", "").strip().lower()
    if secure_flag in ("1", "true", "yes"):
        secure = True
    elif secure_flag in ("0", "false", "no"):
        secure = False
    else:
        secure = APP_ENV in ("production", "prod")

    kwargs: dict[str, Any] = {
        "key": POS_ACCESS_COOKIE,
        "value": access_token,
        "httponly": True,
        "samesite": "lax",
        "max_age": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "path": "/",
        "secure": secure,
    }
    domain = os.environ.get("POS_COOKIE_DOMAIN", "").strip()
    if domain:
        kwargs["domain"] = domain
    response.set_cookie(**kwargs)


def clear_access_cookie(response: Response) -> None:
    """Clear the POS access cookie (match path/domain used at set time)."""
    import os

    kwargs: dict[str, Any] = {"key": POS_ACCESS_COOKIE, "path": "/"}
    domain = os.environ.get("POS_COOKIE_DOMAIN", "").strip()
    if domain:
        kwargs["domain"] = domain
    response.delete_cookie(**kwargs)


def attach_access_cookie(response: Response, access_token: str) -> Response:
    """Shared helper: stamp the POS access cookie onto any login response."""
    set_access_cookie(response, access_token)
    return response


def user_from_access_cookie(request: Request, db: Session) -> Optional[User]:
    """Resolve the signed-in user from the HttpOnly access cookie (HTML gate)."""
    token = request.cookies.get(POS_ACCESS_COOKIE)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        username = payload.get("sub")
        if not username:
            return None
        tid_claim = payload.get("tid")
    except JWTError:
        return None
    user = get_user_by_username(db, username=username)
    if user is None or not user.is_active:
        return None
    if user.tenant_id is not None:
        if tid_claim is not None and int(tid_claim) != int(user.tenant_id):
            return None
    elif tid_claim is not None:
        return None
    return user
