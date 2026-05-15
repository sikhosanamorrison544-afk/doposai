import os
from pathlib import Path
from typing import List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent

APP_ENV = os.environ.get("APP_ENV", "development").lower()

# Public URLs (browser + deep links). Used in docs, emails, future redirects.
WEB_PUBLIC_URL = os.environ.get("WEB_PUBLIC_URL", "https://doposai.com").rstrip("/")
API_PUBLIC_URL = os.environ.get("API_PUBLIC_URL", "https://api.doposai.com").rstrip("/")

# SaaS / billing (future Paynow, EcoCash webhooks — validate signatures in billing layer)
TRIAL_DAYS_DEFAULT = int(os.environ.get("TRIAL_DAYS", "14"))
OFFLINE_GRACE_HOURS_DEFAULT = int(os.environ.get("OFFLINE_GRACE_HOURS", "72"))
BILLING_WEBHOOK_SECRET = os.environ.get("BILLING_WEBHOOK_SECRET", "").strip()


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

STORE_NAME = "J & B MALL"
STORE_PHONE = ""
STORE_LOCATION = ""
