from datetime import datetime, timedelta
import hashlib
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import func
from sqlalchemy.orm import Session

import os
from .config import PWD_HASH_SCHEME
from .database import get_db
from .models import User

# NOTE: For production, use environment variable for SECRET_KEY
# Generate a secure key using: python -c "import secrets; print(secrets.token_urlsafe(32))"
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-this-to-a-long-random-string-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 8 * 60  # 8 hours
REFRESH_TOKEN_EXPIRE_DAYS = 30

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
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


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
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return current_user


