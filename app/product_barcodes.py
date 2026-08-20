"""Auto-assigned product barcodes (AUTO-XXXXXX).

Uniqueness: database enforces global ``Product.barcode`` unique. Generation
scans the current tenant sequence then verifies no global collision before
insert. Concurrent creates retry on IntegrityError.
"""
from __future__ import annotations

from typing import Optional, Set

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Product, User
from . import tenant_scope

_AUTO_PREFIX = "AUTO-"
_MAX_ATTEMPTS = 50


def _max_auto_number(barcodes: list) -> int:
    max_num = 0
    for (barcode,) in barcodes:
        if not barcode or not str(barcode).startswith(_AUTO_PREFIX):
            continue
        try:
            num_str = str(barcode).split("-", 1)[1] if "-" in str(barcode) else ""
            num = int(num_str) if num_str.isdigit() else 0
            max_num = max(max_num, num)
        except (ValueError, IndexError):
            continue
    return max_num


def _barcode_taken_globally(db: Session, code: str) -> bool:
    return db.query(Product.id).filter(Product.barcode == code).first() is not None


def generate_unique_barcode(db: Session, user: User) -> str:
    """Generate a unique auto-assigned barcode in format AUTO-XXXXXX."""
    existing_auto_barcodes = (
        tenant_scope.filter_products(db, user)
        .with_entities(Product.barcode)
        .filter(Product.barcode.like(f"{_AUTO_PREFIX}%"))
        .all()
    )
    next_num = _max_auto_number(existing_auto_barcodes) + 1

    for _ in range(_MAX_ATTEMPTS):
        new_barcode = f"{_AUTO_PREFIX}{next_num:06d}"
        if not _barcode_taken_globally(db, new_barcode):
            return new_barcode
        next_num += 1

    raise RuntimeError("Unable to allocate a unique product barcode")


def ensure_product_barcode(db: Session, product: Product, user: User) -> str:
    """Assign AUTO-* barcode if the product has none (legacy backfill on edit/restock)."""
    if product.barcode and str(product.barcode).strip():
        return str(product.barcode).strip()
    code = generate_unique_barcode(db, user)
    product.barcode = code
    return code


class AutoBarcodeAllocator:
    """Fast sequential AUTO-* codes during bulk import (one DB scan at start)."""

    def __init__(self, db: Session, user: User) -> None:
        rows = (
            tenant_scope.filter_products(db, user)
            .with_entities(Product.barcode)
            .filter(Product.barcode.like(f"{_AUTO_PREFIX}%"))
            .all()
        )
        self._next_num = _max_auto_number(rows) + 1
        self._reserved: Set[str] = set()
        self._db = db
        self._user = user

    def reserve(self, barcode: Optional[str]) -> None:
        if barcode:
            self._reserved.add(barcode.lower())

    def allocate(self) -> str:
        while True:
            code = f"{_AUTO_PREFIX}{self._next_num:06d}"
            self._next_num += 1
            key = code.lower()
            if key in self._reserved:
                continue
            if _barcode_taken_globally(self._db, code):
                self._reserved.add(key)
                continue
            self._reserved.add(key)
            return code


# Re-export for callers that catch IntegrityError on insert races
__all__ = [
    "generate_unique_barcode",
    "ensure_product_barcode",
    "AutoBarcodeAllocator",
    "IntegrityError",
]
