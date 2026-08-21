"""Business (store) currency helpers — ISO 4217 display codes."""
from __future__ import annotations

from typing import Optional

# Common retail currencies; others allowed if they match ISO 4217 shape.
KNOWN_CURRENCIES = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "ZAR",
        "ZWL",
        "ZWG",
        "BWP",
        "MWK",
        "MZN",
        "NAD",
        "KES",
        "TZS",
        "UGX",
        "NGN",
        "GHS",
        "CAD",
        "AUD",
        "INR",
        "CNY",
        "JPY",
        "CHF",
        "AED",
    }
)

DEFAULT_CURRENCY = "USD"


def normalize_currency(code: Optional[str], *, default: str = DEFAULT_CURRENCY) -> str:
    raw = (code or "").strip().upper()
    if len(raw) == 3 and raw.isalpha():
        return raw
    return default


def validate_currency(code: Optional[str]) -> str:
    """Return normalized code or raise ValueError."""
    raw = (code or "").strip().upper()
    if len(raw) != 3 or not raw.isalpha():
        raise ValueError("Currency must be a 3-letter ISO 4217 code (e.g. USD, ZAR)")
    return raw
