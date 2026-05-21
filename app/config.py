from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent

APP_ENV = os.environ.get("APP_ENV", "development").lower()

# Public URLs (browser + deep links). Used in docs, emails, future redirects.
WEB_PUBLIC_URL = os.environ.get("WEB_PUBLIC_URL", "https://doposai.com").rstrip("/")
API_PUBLIC_URL = os.environ.get("API_PUBLIC_URL", "https://api.doposai.com").rstrip("/")

# SaaS / billing (Paynow + EcoCash)
TRIAL_DAYS_DEFAULT = int(os.environ.get("TRIAL_DAYS", "14"))
OFFLINE_GRACE_HOURS_DEFAULT = int(os.environ.get("OFFLINE_GRACE_HOURS", "72"))
BILLING_WEBHOOK_SECRET = os.environ.get("BILLING_WEBHOOK_SECRET", "").strip()
PAYNOW_INTEGRATION_ID = os.environ.get("PAYNOW_INTEGRATION_ID", "").strip()
PAYNOW_INTEGRATION_KEY = os.environ.get("PAYNOW_INTEGRATION_KEY", "").strip()
PAYNOW_RETURN_URL = os.environ.get("PAYNOW_RETURN_URL", "").strip()
PAYNOW_RESULT_URL = os.environ.get("PAYNOW_RESULT_URL", "").strip()


def _normalize_database_url() -> str:
    """Local default is repo SQLite; cloud (e.g. Render) sets DATABASE_URL."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{BASE_DIR / 'pos.db'}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = _normalize_database_url()


def get_cors_origins_and_credentials() -> Tuple[List[str], bool]:
    """
    Returns (origins, allow_credentials).
    allow_credentials=False when using wildcard origin (browser restriction).
    """
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "").strip()
    if raw == "*":
        return ["*"], False
    if not raw:
        return [
            "https://doposai.com",
            "https://www.doposai.com",
            "https://api.doposai.com",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ], True
    parts = [p.strip().rstrip("/") for p in raw.split(",") if p.strip()]
    if not parts:
        return (
            [
                "https://doposai.com",
                "https://www.doposai.com",
                "https://api.doposai.com",
            ],
            True,
        )
    if "*" in parts:
        return ["*"], False
    return parts, True


# ESC/POS printer device path (adjust for your Pi/printer)
PRINTER_DEVICE = "/dev/usb/lp0"

PWD_HASH_SCHEME = "pbkdf2_sha256"

# PLATFORM_BRAND_NAME is the platform-wide brand (e.g. shown on the public
# login screen, in password-reset emails, on billing line items). It is
# DISTINCT from per-tenant store names, which are stored in StoreSettings
# and used inside the tenant's own UI/receipts. Falls back to STORE_NAME
# below so older deployments that only set STORE_NAME still get a sane
# default.
PLATFORM_BRAND_NAME = (
    os.environ.get("PLATFORM_BRAND_NAME", "").strip() or "All In One POS"
)

# STORE_NAME is the per-tenant fallback used when a tenant has not set its
# own StoreSettings.store_name yet (fresh signups, etc). We default it to
# the platform brand so unbranded views never show "POS".
STORE_NAME = (os.environ.get("STORE_NAME", "").strip() or PLATFORM_BRAND_NAME)
STORE_PHONE = os.environ.get("STORE_PHONE", "").strip()
STORE_LOCATION = os.environ.get("STORE_LOCATION", "").strip()


def _parse_platform_owner_usernames() -> frozenset[str]:
    """
    Comma-separated usernames (case-insensitive) allowed to use /platform/tenants
    and GET /api/platform/tenants. Must be admin accounts. Set env e.g.:
    PLATFORM_OWNER_USERNAMES=morrison,owner

    WARNING — usernames are NOT globally unique across tenants. Every tenant's
    first user defaults to ``admin``, so setting this to ``admin`` grants
    platform-owner access to every tenant's primary admin. For SaaS
    deployments prefer PLATFORM_OWNER_EMAILS below, which IS globally unique.
    """
    raw = os.environ.get("PLATFORM_OWNER_USERNAMES", "").strip()
    if not raw:
        return frozenset()
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def _parse_platform_owner_emails() -> frozenset[str]:
    """
    Comma-separated emails (case-insensitive) allowed to use /platform/tenants.
    Recommended over PLATFORM_OWNER_USERNAMES for SaaS because emails are
    globally unique across tenants. Example:
        PLATFORM_OWNER_EMAILS=you@example.com,cofounder@example.com
    """
    raw = os.environ.get("PLATFORM_OWNER_EMAILS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


# Parsed once at import; restart app after changing env.
PLATFORM_OWNER_USERNAMES: frozenset[str] = _parse_platform_owner_usernames()
PLATFORM_OWNER_EMAILS: frozenset[str] = _parse_platform_owner_emails()
