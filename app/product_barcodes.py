"""Auto-assigned product barcodes (AUTO-XXXXXX).

Uniqueness: ``Product.barcode`` is globally unique (database index). Allocation
therefore uses the SAME global namespace as the database constraint — the
maximum valid ``AUTO-`` numeric suffix across ALL tenants is the starting
point, then increments while a candidate is globally occupied.

Automatic barcode allocation is the only global operation here. Product
visibility, ownership, and tenant scoping elsewhere are unchanged.

Only barcode values matching ``AUTO-%`` are scanned (never full Product models),
so a database sequence can replace this max-scan later without touching callers.
"""
from __future__ import annotations

from typing import Optional, Set, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Product, User

_AUTO_PREFIX = "AUTO-"

# Practically unreachable: even 1M consecutive collisions implies the namespace
# is exhausted. Used only as a defensive guard, never as the normal retry limit.
ALLOCATION_SAFETY_LIMIT = 1_000_000


class BarcodeAllocationError(Exception):
    """Raised when the global AUTO-* namespace cannot allocate a unique code."""


def _parse_auto_suffix(barcode: Optional[str]) -> Optional[int]:
    """Return the numeric suffix of an AUTO-* barcode, or None if malformed."""
    if not barcode:
        return None
    s = str(barcode)
    if not s.startswith(_AUTO_PREFIX):
        return None
    suffix = s[len(_AUTO_PREFIX):]
    if not suffix.isdigit():
        return None
    try:
        return int(suffix)
    except ValueError:
        return None


def _global_auto_state(db: Session) -> Tuple[int, Set[str]]:
    """One query returning (global_max_AUTO_suffix, global_AUTO_barcode_set).

    Scans only barcode string values matching ``AUTO-%``; loads no Product
    models and applies no tenant scoping.
    """
    rows = (
        db.query(Product.barcode)
        .filter(Product.barcode.like(f"{_AUTO_PREFIX}%"))
        .all()
    )
    max_num = 0
    taken: Set[str] = set()
    for (barcode,) in rows:
        if not barcode:
            continue
        s = str(barcode)
        if not s.startswith(_AUTO_PREFIX):
            continue
        taken.add(s)
        n = _parse_auto_suffix(s)
        if n is not None:
            max_num = max(max_num, n)
    return max_num, taken


def generate_unique_barcode(db: Session, user: Optional[User] = None) -> str:
    """Generate a unique auto-assigned barcode in format AUTO-XXXXXX.

    Uses the global AUTO-* namespace: starts after the global maximum valid
    suffix and increments while a candidate is globally occupied.
    """
    next_num, taken = _global_auto_state(db)
    next_num += 1

    for _ in range(ALLOCATION_SAFETY_LIMIT):
        code = f"{_AUTO_PREFIX}{next_num:06d}"
        if code not in taken:
            return code
        next_num += 1

    raise BarcodeAllocationError(
        "Unable to allocate a unique AUTO barcode: global namespace exhausted"
    )


def ensure_product_barcode(
    db: Session, product: Product, user: Optional[User] = None
) -> str:
    """Assign AUTO-* barcode if the product has none (legacy backfill on edit/restock)."""
    if product.barcode and str(product.barcode).strip():
        return str(product.barcode).strip()
    code = generate_unique_barcode(db, user)
    product.barcode = code
    return code


class AutoBarcodeAllocator:
    """Fast sequential AUTO-* codes during bulk import (one global DB scan at start).

    Reserves during the current import to avoid:
      - existing global database AUTO-* barcodes (snapshot at init);
      - duplicate explicit barcodes within the file (``reserve``);
      - duplicate automatically allocated codes within the file.
    The database unique index remains the final authority.
    """

    def __init__(self, db: Session, user: Optional[User] = None) -> None:
        global_max, global_taken = _global_auto_state(db)
        self._next_num = global_max + 1
        self._global_taken: Set[str] = global_taken
        self._reserved: Set[str] = set()
        self._db = db
        self._user = user

    def reserve(self, barcode: Optional[str]) -> None:
        if barcode:
            self._reserved.add(str(barcode).lower())

    def allocate(self) -> str:
        for _ in range(ALLOCATION_SAFETY_LIMIT):
            code = f"{_AUTO_PREFIX}{self._next_num:06d}"
            self._next_num += 1
            key = code.lower()
            if key in self._reserved or code in self._global_taken:
                continue
            self._reserved.add(key)
            return code
        raise BarcodeAllocationError(
            "Unable to allocate a unique AUTO barcode during import"
        )


# Re-export for callers that catch IntegrityError on insert races
__all__ = [
    "BarcodeAllocationError",
    "generate_unique_barcode",
    "ensure_product_barcode",
    "AutoBarcodeAllocator",
    "IntegrityError",
]