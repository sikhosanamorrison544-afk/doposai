"""Meta webhook signature verification (X-Hub-Signature-256, HMAC-SHA256)."""
from __future__ import annotations

import hashlib
import hmac
from typing import Optional


def compute_signature(app_secret: str, raw_body: bytes) -> str:
    """Return the value Meta will send in X-Hub-Signature-256."""
    mac = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify_meta_signature(
    raw_body: bytes,
    header_value: Optional[str],
    app_secret: str,
) -> bool:
    """Constant-time compare the incoming signature to the expected HMAC.

    Returns False on any defect — missing header, wrong prefix, length
    mismatch, secret unset — so callers can simply ``if not verify(...)``.
    """
    if not app_secret or not header_value:
        return False
    if not header_value.startswith("sha256="):
        return False
    expected = compute_signature(app_secret, raw_body)
    return hmac.compare_digest(expected, header_value)
