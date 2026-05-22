"""Product inventory import: merge stock, match existing rows, avoid duplicates."""
from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import InventoryMovement, Product, User
from . import tenant_scope

logger = logging.getLogger(__name__)


def normalize_product_name(name: str) -> str:
    return " ".join((name or "").strip().split())


def normalize_barcode(code: str) -> Optional[str]:
    c = (code or "").strip()
    if not c:
        return None
    # Excel often exports long numeric barcodes as scientific notation (e.g. 6.98E+12)
    if re.match(r"^\d+\.?\d*[eE][+\-]?\d+$", c):
        try:
            c = str(int(float(c)))
        except (ValueError, OverflowError):
            pass
    return c if c else None


IMPORT_COMMIT_BATCH = 250
MAX_IMPORT_ERRORS_REPORTED = 50


class ProductIndex:
    """In-memory product lookup for fast CSV import (avoids per-row DB queries)."""

    def __init__(self) -> None:
        self.by_id: Dict[int, Product] = {}
        self.by_barcode: Dict[str, Product] = {}
        self.by_name_lower: Dict[str, List[Product]] = {}

    @classmethod
    def from_products(cls, products: List[Product]) -> "ProductIndex":
        idx = cls()
        for product in products:
            idx.register(product)
        return idx

    def register(self, product: Product) -> None:
        if product.id is not None:
            self.by_id[int(product.id)] = product
        barcode = normalize_barcode(str(product.barcode or ""))
        if barcode:
            self.by_barcode[barcode] = product
        key = normalize_product_name(product.name).lower()
        if key:
            bucket = self.by_name_lower.setdefault(key, [])
            if product not in bucket:
                bucket.append(product)

    def get(self, product_id: int) -> Optional[Product]:
        return self.by_id.get(int(product_id))

    def find(self, name: str, barcode: Optional[str]) -> Optional[Product]:
        if barcode:
            hit = self.by_barcode.get(barcode)
            if hit:
                return hit
        clean = normalize_product_name(name)
        if not clean:
            return None
        matches = self.by_name_lower.get(clean.lower(), [])
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        exact = [m for m in matches if normalize_product_name(m.name) == clean]
        if len(exact) == 1:
            return exact[0]
        return matches[0]


def find_existing_product(
    pq,
    name: str,
    barcode: Optional[str],
) -> Optional[Product]:
    """
    Find one existing product for this tenant: barcode first, then case-insensitive name.
    If several products share a name, prefer exact name match, else oldest row.
    """
    if barcode:
        by_barcode = pq.filter(Product.barcode == barcode).first()
        if by_barcode:
            return by_barcode

    clean = normalize_product_name(name)
    if not clean:
        return None

    matches = (
        pq.filter(func.lower(Product.name) == clean.lower())
        .order_by(Product.id.asc())
        .all()
    )
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    exact = [m for m in matches if normalize_product_name(m.name) == clean]
    if len(exact) == 1:
        return exact[0]
    return matches[0]


def _pending_name_key(name: str) -> str:
    return f"n:{normalize_product_name(name).lower()}"


def _pending_barcode_key(barcode: str) -> str:
    return f"b:{barcode}"


def _register_pending(
    pending: Dict[str, int], product_id: int, name: str, barcode: Optional[str]
) -> None:
    pending[_pending_name_key(name)] = product_id
    if barcode:
        pending[_pending_barcode_key(barcode)] = product_id


def _lookup_pending(
    pending: Dict[str, int], name: str, barcode: Optional[str]
) -> Optional[int]:
    if barcode:
        pid = pending.get(_pending_barcode_key(barcode))
        if pid is not None:
            return pid
    return pending.get(_pending_name_key(name))


def _apply_import_prices(
    product: Product,
    *,
    avg_cost: Decimal,
    selling_price: Decimal,
    has_cost: bool,
    has_price: bool,
    is_new: bool,
) -> None:
    """Apply cost/selling from CSV; on updates, do not wipe prices when columns are missing."""
    if is_new or has_cost:
        product.cost_price = avg_cost
    if is_new or has_price:
        product.selling_price = selling_price


def merge_product_from_import(
    db: Session,
    pq,
    existing: Product,
    *,
    name: str,
    category_id: Optional[int],
    avg_cost: Decimal,
    selling_price: Decimal,
    has_cost: bool,
    has_price: bool,
    has_stock: bool,
    stock_mode: str,
    stock_qty: float,
    barcode: Optional[str],
) -> float:
    """Merge prices and stock; return quantity change recorded."""
    existing.name = normalize_product_name(name) or existing.name
    if category_id is not None:
        existing.category_id = category_id
    _apply_import_prices(
        existing,
        avg_cost=avg_cost,
        selling_price=selling_price,
        has_cost=has_cost,
        has_price=has_price,
        is_new=False,
    )
    existing.is_active = True

    if barcode and not existing.barcode:
        conflict = pq.filter(
            Product.barcode == barcode,
            Product.id != existing.id,
        ).first()
        if not conflict:
            existing.barcode = barcode

    qty = max(0.0, float(stock_qty))
    delta = 0.0
    if has_stock:
        before = float(existing.stock_qty or 0)
        if stock_mode == "set":
            existing.stock_qty = qty
            delta = qty - before
        else:
            existing.stock_qty = before + qty
            delta = qty
    db.flush()

    if has_stock and abs(delta) > 1e-9:
        reason = (
            f"Stock set to {qty} (file import)"
            if stock_mode == "set"
            else f"Stock merge (file import: +{delta})"
        )
        db.add(
            InventoryMovement(
                product_id=existing.id,
                change_qty=delta,
                reason=reason,
            )
        )
    return delta


def _create_product_from_import(
    db: Session,
    *,
    tenant_id: Optional[int],
    name: str,
    barcode: Optional[str],
    category_id: Optional[int],
    avg_cost: Decimal,
    selling_price: Decimal,
    has_cost: bool,
    has_price: bool,
    in_hand_stock: float,
) -> Optional[Product]:
    """Insert a new product; retry without barcode if barcode is globally duplicate."""

    def _build(bcode: Optional[str]) -> Product:
        p = Product(
            name=name,
            barcode=bcode,
            category_id=category_id,
            stock_qty=max(0.0, in_hand_stock),
            cost_price=Decimal("0.00"),
            selling_price=Decimal("0.00"),
            is_active=True,
            tenant_id=tenant_id,
        )
        _apply_import_prices(
            p,
            avg_cost=avg_cost,
            selling_price=selling_price,
            has_cost=has_cost,
            has_price=has_price,
            is_new=True,
        )
        return p

    attempts: List[Optional[str]] = [barcode] if barcode else [None]
    if barcode:
        attempts.append(None)
    for attempt_barcode in attempts:
        try:
            with db.begin_nested():
                product = _build(attempt_barcode)
                db.add(product)
                db.flush()
                if in_hand_stock > 0:
                    db.add(
                        InventoryMovement(
                            product_id=product.id,
                            change_qty=in_hand_stock,
                            reason="Initial stock (file import)",
                        )
                    )
                    db.flush()
            return product
        except IntegrityError:
            if attempt_barcode is None:
                return None
            continue
    return None


def _resolve_category_id(
    db: Session,
    current_admin: User,
    category_name: str,
    cache: Dict[str, int],
) -> Optional[int]:
    from .models import Category

    if not category_name or not category_name.strip():
        return None
    name = category_name.strip()
    if name in cache:
        return cache[name]
    cat = tenant_scope.filter_categories(db, current_admin).filter(Category.name == name).first()
    if not cat:
        cat = Category(
            name=name,
            description=None,
            tenant_id=tenant_scope.tenant_id_for_row(current_admin),
        )
        db.add(cat)
        db.flush()
    cache[name] = cat.id
    return cat.id


def _record_import_error(stats: Dict[str, Any], row_num: int, message: str) -> None:
    stats["skipped"] += 1
    if len(stats["errors"]) < MAX_IMPORT_ERRORS_REPORTED:
        stats["errors"].append(f"Row {row_num}: {message}")


def import_products_into_db(
    db: Session,
    current_admin: User,
    products_data: List[dict],
    get_or_create_category,
) -> Dict[str, Any]:
    """
    Import rows into products for the current tenant.
    - Matches existing by barcode or name (merge stock).
    - Duplicate rows in the same file merge into one product.
    """
    from .inventory_csv import merge_import_rows

    products_data, file_merged = merge_import_rows(products_data)

    stats: Dict[str, Any] = {
        "total_rows": len(products_data),
        "created": 0,
        "updated": 0,
        "merged_rows": 0,
        "file_merged_rows": file_merged,
        "skipped": 0,
        "errors": [],
        "stock_mode": products_data[0].get("stock_mode", "add") if products_data else "add",
    }
    pq = tenant_scope.filter_products(db, current_admin)
    tenant_id = tenant_scope.tenant_id_for_row(current_admin)
    product_index = ProductIndex.from_products(pq.all())
    category_ids: Dict[str, int] = {}
    pending: Dict[str, int] = {}
    rows_since_commit = 0

    def _finish_row(product: Product, name: str, barcode: Optional[str]) -> None:
        product_index.register(product)
        _register_pending(pending, product.id, name, barcode)

    for row_num, product_data in enumerate(products_data, start=1):
        try:
            with db.begin_nested():
                product_name = normalize_product_name(product_data.get("name", ""))
                if not product_name:
                    raise ValueError("Missing product name")

                product_code = normalize_barcode(str(product_data.get("code", "") or ""))
                category_name = (product_data.get("category") or "").strip()
                avg_cost = product_data.get("cost", Decimal("0.00"))
                selling_price = product_data.get("price", Decimal("0.00"))
                has_cost = bool(product_data.get("has_cost"))
                has_price = bool(product_data.get("has_price"))
                has_stock = bool(product_data.get("has_stock"))
                stock_mode = str(product_data.get("stock_mode") or "add")
                in_hand_stock = max(0.0, float(product_data.get("stock", 0.0)))
                product_id = product_data.get("product_id")
                category_id = _resolve_category_id(
                    db, current_admin, category_name, category_ids
                )

                pending_id = _lookup_pending(pending, product_name, product_code)

                if product_id is not None:
                    by_id = product_index.get(int(product_id))
                    if by_id:
                        merge_product_from_import(
                            db,
                            pq,
                            by_id,
                            name=product_name,
                            category_id=category_id,
                            avg_cost=avg_cost,
                            selling_price=selling_price,
                            has_cost=has_cost,
                            has_price=has_price,
                            has_stock=has_stock,
                            stock_mode=stock_mode,
                            stock_qty=in_hand_stock,
                            barcode=product_code,
                        )
                        _finish_row(by_id, product_name, product_code)
                        stats["updated"] += 1
                    else:
                        raise ValueError(f"Product ID {product_id} not found")
                elif pending_id is not None:
                    existing = product_index.get(pending_id)
                    if not existing:
                        raise ValueError("Pending product row missing from database")
                    merge_product_from_import(
                        db,
                        pq,
                        existing,
                        name=product_name,
                        category_id=category_id,
                        avg_cost=avg_cost,
                        selling_price=selling_price,
                        has_cost=has_cost,
                        has_price=has_price,
                        has_stock=has_stock,
                        stock_mode=stock_mode,
                        stock_qty=in_hand_stock,
                        barcode=product_code,
                    )
                    _finish_row(existing, product_name, product_code)
                    stats["merged_rows"] += 1
                    stats["updated"] += 1
                else:
                    existing_product = product_index.find(product_name, product_code)
                    if existing_product:
                        merge_product_from_import(
                            db,
                            pq,
                            existing_product,
                            name=product_name,
                            category_id=category_id,
                            avg_cost=avg_cost,
                            selling_price=selling_price,
                            has_cost=has_cost,
                            has_price=has_price,
                            has_stock=has_stock,
                            stock_mode=stock_mode,
                            stock_qty=in_hand_stock,
                            barcode=product_code,
                        )
                        _finish_row(existing_product, product_name, product_code)
                        stats["updated"] += 1
                    else:
                        barcode = product_code
                        merged = False
                        if barcode:
                            conflict = product_index.by_barcode.get(barcode)
                            if conflict and conflict.name.strip().lower() != product_name.lower():
                                by_name = product_index.find(product_name, None)
                                if by_name:
                                    merge_product_from_import(
                                        db,
                                        pq,
                                        by_name,
                                        name=product_name,
                                        category_id=category_id,
                                        avg_cost=avg_cost,
                                        selling_price=selling_price,
                                        has_cost=has_cost,
                                        has_price=has_price,
                                        has_stock=has_stock,
                                        stock_mode=stock_mode,
                                        stock_qty=in_hand_stock,
                                        barcode=None,
                                    )
                                    _finish_row(by_name, product_name, product_code)
                                    stats["updated"] += 1
                                    merged = True
                                else:
                                    barcode = None
                            elif conflict:
                                merge_product_from_import(
                                    db,
                                    pq,
                                    conflict,
                                    name=product_name,
                                    category_id=category_id,
                                    avg_cost=avg_cost,
                                    selling_price=selling_price,
                                    has_cost=has_cost,
                                    has_price=has_price,
                                    has_stock=has_stock,
                                    stock_mode=stock_mode,
                                    stock_qty=in_hand_stock,
                                    barcode=barcode,
                                )
                                _finish_row(conflict, product_name, product_code)
                                stats["updated"] += 1
                                merged = True

                        if not merged:
                            again = product_index.find(product_name, None)
                            if again:
                                merge_product_from_import(
                                    db,
                                    pq,
                                    again,
                                    name=product_name,
                                    category_id=category_id,
                                    avg_cost=avg_cost,
                                    selling_price=selling_price,
                                    has_cost=has_cost,
                                    has_price=has_price,
                                    has_stock=has_stock,
                                    stock_mode=stock_mode,
                                    stock_qty=in_hand_stock,
                                    barcode=product_code if not again.barcode else None,
                                )
                                _finish_row(again, product_name, product_code)
                                stats["updated"] += 1
                            else:
                                created = _create_product_from_import(
                                    db,
                                    tenant_id=tenant_id,
                                    name=product_name,
                                    barcode=barcode,
                                    category_id=category_id,
                                    avg_cost=avg_cost,
                                    selling_price=selling_price,
                                    has_cost=has_cost,
                                    has_price=has_price,
                                    in_hand_stock=in_hand_stock,
                                )
                                if created is None:
                                    raise ValueError(
                                        f"Could not create '{product_name}' "
                                        "(duplicate barcode or database error)"
                                    )
                                _finish_row(created, product_name, product_code)
                                stats["created"] += 1

            rows_since_commit += 1
            if rows_since_commit >= IMPORT_COMMIT_BATCH:
                db.commit()
                rows_since_commit = 0
        except Exception as e:
            _record_import_error(stats, row_num, str(e))
            logger.error("Import row %s failed: %s", row_num, e, exc_info=True)

    if rows_since_commit > 0:
        db.commit()

    if stats["skipped"] and len(stats["errors"]) < stats["skipped"]:
        extra = stats["skipped"] - len(stats["errors"])
        stats["errors"].append(f"…and {extra} more row error(s)")

    return stats
