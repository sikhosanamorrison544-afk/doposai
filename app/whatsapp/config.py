"""WhatsApp Cloud API configuration (env-driven)."""
from __future__ import annotations

import os

WHATSAPP_VERIFY_TOKEN: str = os.environ.get("WHATSAPP_VERIFY_TOKEN", "").strip()
WHATSAPP_ACCESS_TOKEN: str = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
WHATSAPP_PHONE_NUMBER_ID: str = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
WHATSAPP_APP_SECRET: str = os.environ.get("WHATSAPP_APP_SECRET", "").strip()
WHATSAPP_API_VERSION: str = os.environ.get("WHATSAPP_API_VERSION", "v21.0").strip()

WHATSAPP_SESSION_TIMEOUT_HOURS: int = int(
    os.environ.get("WHATSAPP_SESSION_TIMEOUT_HOURS", "24")
)
WHATSAPP_MAX_MENU_TENANTS: int = int(
    os.environ.get("WHATSAPP_MAX_MENU_TENANTS", "10")
)
WHATSAPP_BRAND_NAME: str = (
    os.environ.get("WHATSAPP_BRAND_NAME", "").strip() or "Photron Business Hub"
)
WHATSAPP_HUMAN_HANDOVER_NOTICE: str = (
    os.environ.get(
        "WHATSAPP_HUMAN_HANDOVER_NOTICE",
        "Thanks — I've notified the team. Someone will reply shortly. "
        "Type MENU at any time to pick a different business.",
    )
)


def is_configured() -> bool:
    """True if the minimum env vars to receive AND send are set."""
    return bool(
        WHATSAPP_VERIFY_TOKEN
        and WHATSAPP_ACCESS_TOKEN
        and WHATSAPP_PHONE_NUMBER_ID
        and WHATSAPP_APP_SECRET
    )


def graph_base_url() -> str:
    return f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
