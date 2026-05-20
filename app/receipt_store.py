"""Normalize store branding for receipts (name, address, phone always present)."""
from __future__ import annotations

from typing import Optional, Tuple

from .config import STORE_LOCATION, STORE_NAME, STORE_PHONE


def normalize_store_receipt_fields(
    store_name: Optional[str],
    store_phone: Optional[str] = None,
    store_location: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    Return (name, address, phone) for receipt headers.
    Address and phone are always strings (may be empty if not configured).
    """
    name = (store_name or STORE_NAME or "POS").strip()
    address = (store_location or STORE_LOCATION or "").strip()
    phone = (store_phone or STORE_PHONE or "").strip()
    return name, address, phone
