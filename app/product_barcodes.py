"""Auto-assigned product barcodes (AUTO-XXXXXX), per-tenant sequence."""
from __future__ import annotations

from typing import Optional, Set

from sqlalchemy.orm import Session

from .models import Product, User
from . import tenant_scope

_AUTO_PREFIX = "AUTO-"


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


def generate_unique_barcode(db: Session, user: User) -> str:
    """Generate a unique auto-assigned barcode in format AUTO-XXXXXX (per-tenant scan)."""
    existing_auto_barcodes = (
        tenant_scope.filter_products(db, user)
        .with_entities(Product.barcode)
        .filter(Product.barcode.like(f"{_AUTO_PREFIX}%"))
        .all()
    )
    next_num = _max_auto_number(existing_auto_barcodes) + 1
    new_barcode = f"{_AUTO_PREFIX}{next_num:06d}"

    existing = (
        tenant_scope.filter_products(db, user)
        .filter(Product.barcode == new_barcode)
        .first()
    )
    while existing:
        next_num += 1
        new_barcode = f"{_AUTO_PREFIX}{next_num:06d}"
        existing = (
            tenant_scope.filter_products(db, user)
            .filter(Product.barcode == new_barcode)
            .first()
        )
    return new_barcode


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
            hit = (
                tenant_scope.filter_products(self._db, self._user)
                .filter(Product.barcode == code)
                .first()
            )
            if hit:
                self._reserved.add(key)
                continue
            self._reserved.add(key)
            return code
