import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _normalize_database_url() -> str:
    """Local default is repo SQLite; cloud (e.g. Render) sets DATABASE_URL."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{BASE_DIR / 'pos.db'}"
    # Render / Heroku style
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = _normalize_database_url()

# ESC/POS printer device path (adjust for your Pi/printer)
# Common examples: '/dev/usb/lp0', '/dev/ttyUSB0'
PRINTER_DEVICE = "/dev/usb/lp0"

# Password hashing configuration
# Use a pure-Python scheme to avoid native bcrypt issues on some platforms.
PWD_HASH_SCHEME = "pbkdf2_sha256"

# Store information
STORE_NAME = "J & B MALL"
STORE_PHONE = ""  # Add your shop phone number here
STORE_LOCATION = ""  # Add your shop location/address here


