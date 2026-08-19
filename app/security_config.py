"""
Centralized authentication security settings.

JWT secrets and bootstrap passwords must come from the operator environment
or an interactive local CLI — never from source-code defaults.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

# HS256 is the only algorithm this application issues and accepts.
JWT_ALGORITHM = "HS256"
JWT_SECRET_ENV = "JWT_SECRET_KEY"
JWT_MIN_SECRET_LENGTH = 32

# Exact values (case-insensitive) that must never be used as JWT secrets.
_JWT_PLACEHOLDER_SECRETS = frozenset(
    {
        "",
        "secret",
        "dev-secret",
        "devsecret",
        "change-me",
        "change-me-in-production",
        "changeme",
        "your-secret-key",
        "your_secret_key",
        "jwt_secret",
        "jwt-secret",
        "jwtsecret",
        "password",
        "admin",
        "change-this-to-a-long-random-string-in-production",
    }
)

_JWT_PLACEHOLDER_SUBSTRINGS = (
    "change-this-to-a-long-random",
    "change-me-in-production",
    "your-secret-key",
)

# Predictable passwords rejected for bootstrap / repair / factory-reset.
_WEAK_PASSWORDS = frozenset(
    {
        "admin",
        "password",
        "password1",
        "password123",
        "123456",
        "12345678",
        "qwerty",
        "letmein",
        "welcome",
        "morrison",
        "changeme",
        "default",
        "passw0rd",
        "admin123",
        "root",
        "test",
        "test123",
    }
)

_PASSWORD_MIN_LENGTH = 12


class JwtSecretError(ValueError):
    """Raised when JWT_SECRET_KEY is missing, weak, or a known placeholder."""


class WeakPasswordError(ValueError):
    """Raised when a bootstrap/recovery password is too weak."""


def _load_dotenv_file() -> None:
    """
    Load KEY=VALUE pairs from the repo `.env` into os.environ when unset.

    Does not override variables already present in the process environment.
    Does not invent secrets — the file must contain a real JWT_SECRET_KEY.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ[key] = value


def validate_jwt_secret(raw: Optional[str]) -> str:
    """Return a validated JWT signing secret or raise JwtSecretError."""
    if raw is None:
        raise JwtSecretError(
            f"{JWT_SECRET_ENV} is not set. Generate one with "
            "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
            "and put it in your environment or .env file."
        )
    secret = raw.strip()
    if not secret:
        raise JwtSecretError(f"{JWT_SECRET_ENV} is empty.")
    lowered = secret.lower()
    if lowered in _JWT_PLACEHOLDER_SECRETS:
        raise JwtSecretError(
            f"{JWT_SECRET_ENV} is a known insecure placeholder. "
            "Set a unique random secret of at least "
            f"{JWT_MIN_SECRET_LENGTH} characters."
        )
    for needle in _JWT_PLACEHOLDER_SUBSTRINGS:
        if needle in lowered:
            raise JwtSecretError(
                f"{JWT_SECRET_ENV} looks like a documentation placeholder. "
                "Replace it with a unique random secret."
            )
    if len(secret) < JWT_MIN_SECRET_LENGTH:
        raise JwtSecretError(
            f"{JWT_SECRET_ENV} must be at least {JWT_MIN_SECRET_LENGTH} characters."
        )
    return secret


def load_jwt_secret_from_env() -> str:
    """Load and validate JWT_SECRET_KEY from the process environment (and optional .env)."""
    _load_dotenv_file()
    return validate_jwt_secret(os.environ.get(JWT_SECRET_ENV))


def validate_bootstrap_password(password: Optional[str]) -> str:
    """
    Validate a password for admin bootstrap, factory reset, or local repair.

    Does not log or echo the password.
    """
    if password is None:
        raise WeakPasswordError("Password is required.")
    # Do not strip interior spaces; only reject empty after strip of ends.
    pwd = password.strip()
    if not pwd:
        raise WeakPasswordError("Password is required.")
    if len(pwd) < _PASSWORD_MIN_LENGTH:
        raise WeakPasswordError(
            f"Password must be at least {_PASSWORD_MIN_LENGTH} characters."
        )
    if pwd.lower() in _WEAK_PASSWORDS:
        raise WeakPasswordError("Password is too common or is a default value.")
    if pwd.lower() == "admin":
        raise WeakPasswordError("Password must not be the default administrator password.")
    # Require at least one letter and one digit for bootstrap paths.
    if not re.search(r"[A-Za-z]", pwd) or not re.search(r"\d", pwd):
        raise WeakPasswordError(
            "Password must contain at least one letter and one digit."
        )
    return pwd
