"""Receipt Design settings helpers (defaults, validation, render resolution)."""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

DEFAULT_RECEIPT_KEEP_FOR_REFUND = "Keep receipt for refund"
DEFAULT_RECEIPT_FOOTER = "Thank you for shopping with us!"

MAX_RECEIPT_PHONES = 3
MAX_KEEP_FOR_REFUND_LEN = 200
MAX_FOOTER_LEN = 500
MAX_PHONE_LEN = 32


def normalize_optional_text(value: Optional[str], *, max_len: int) -> Optional[str]:
    """Return stripped text, empty string when blank, or None when unset."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return ""
    return text[:max_len]


def normalize_phone(value: Optional[str]) -> Optional[str]:
    return normalize_optional_text(value, max_len=MAX_PHONE_LEN)


def receipt_phones_from_settings(settings: Any) -> List[str]:
    """Configured receipt phones only (skips blanks). Max 3."""
    if settings is None:
        return []
    out: List[str] = []
    for attr in ("receipt_phone_1", "receipt_phone_2", "receipt_phone_3"):
        raw = getattr(settings, attr, None)
        phone = (str(raw).strip() if raw is not None else "")
        if phone:
            out.append(phone[:MAX_PHONE_LEN])
        if len(out) >= MAX_RECEIPT_PHONES:
            break
    return out


def resolve_keep_for_refund_text(settings: Any) -> Optional[str]:
    """
    NULL/missing → default message.
    Explicit empty string → hide.
    Non-empty → configured text.
    """
    if settings is None:
        return DEFAULT_RECEIPT_KEEP_FOR_REFUND
    if not hasattr(settings, "receipt_keep_for_refund_text"):
        return DEFAULT_RECEIPT_KEEP_FOR_REFUND
    raw = getattr(settings, "receipt_keep_for_refund_text")
    if raw is None:
        return DEFAULT_RECEIPT_KEEP_FOR_REFUND
    text = str(raw).strip()
    return text[:MAX_KEEP_FOR_REFUND_LEN] if text else None


def resolve_receipt_footer(settings: Any) -> Optional[str]:
    """
    NULL/missing → default footer.
    Explicit empty string → hide.
    Non-empty → configured footer (line breaks preserved).
    """
    if settings is None:
        return DEFAULT_RECEIPT_FOOTER
    if not hasattr(settings, "receipt_footer"):
        return DEFAULT_RECEIPT_FOOTER
    raw = getattr(settings, "receipt_footer")
    if raw is None:
        return DEFAULT_RECEIPT_FOOTER
    # Preserve internal newlines; trim only outer whitespace.
    text = str(raw).strip("\r\n")
    if text.strip() == "":
        return None
    return text[:MAX_FOOTER_LEN]


def validate_receipt_phones(phones: Sequence[Optional[str]]) -> List[Optional[str]]:
    """Normalize up to 3 phones; reject lists longer than 3."""
    if len(phones) > MAX_RECEIPT_PHONES:
        raise ValueError(f"At most {MAX_RECEIPT_PHONES} receipt phone numbers are allowed")
    normalized = [normalize_phone(p) for p in phones]
    while len(normalized) < MAX_RECEIPT_PHONES:
        normalized.append(None)
    return normalized[:MAX_RECEIPT_PHONES]


def compose_sale_receipt_closing(settings: Any = None) -> str:
    """
    Build the post-payment receipt closing block (plain text, newlines preserved).

    Order:
      keep-for-refund (if any)
      Phone: + configured receipt phones (blanks omitted; no blank lines)
      footer (if any; line breaks preserved)
    """
    parts: List[str] = []
    keep = resolve_keep_for_refund_text(settings)
    if keep:
        parts.append(keep)
    phones = receipt_phones_from_settings(settings)
    if phones:
        parts.append("Phone:")
        parts.extend(phones)
    footer = resolve_receipt_footer(settings)
    if footer:
        parts.append(footer)
    return "\n".join(parts)
