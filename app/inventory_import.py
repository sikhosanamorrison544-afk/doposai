"""Product inventory import: merge stock, match existing rows, avoid duplicates."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import InventoryMovement, Product, User
from . import tenant_scope

logger = logging.getLogger(__name__)


def normalize_product_name(name: str) -> str:
    return " ".join((name or "").strip().split())


def normalize_barcode(code: str) -> Optional[str]:
    c = (code or "").strip()
    return c if c else None


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


def merge_product_from_import(
    db: Session,
    pq,
    existing: Product,
    *,
    name: str,
    category_id: Optional[int],
    avg_cost: Decimal,
    selling_price: Decimal,
    stock_to_add: float,
    barcode: Optional[str],
) -> float:
    """Add stock and refresh prices; return quantity added."""
    existing.name = normalize_product_name(name) or existing.name
    existing.category_id = category_id
    existing.cost_price = avg_cost
    existing.selling_price = selling_price
    existing.is_active = True

    if barcode and not existing.barcode:
        conflict = pq.filter(
            Product.barcode == barcode,
            Product.id != existing.id,
        ).first()
        if not conflict:
            existing.barcode = barcode

    csv_stock = max(0.0, float(stock_to_add))
    existing.stock_qty = float(existing.stock_qty or 0) + csv_stock
    db.flush()

    if csv_stock > 0:
        db.add(
            InventoryMovement(
                product_id=existing.id,
                change_qty=csv_stock,
                reason=f"Stock merge (file import: +{csv_stock})",
            )
        )
    return csv_stock


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
    stats: Dict[str, Any] = {
        "total_rows": len(products_data),
        "created": 0,
        "updated": 0,
        "merged_rows": 0,
        "skipped": 0,
        "errors": [],
    }
    pq = tenant_scope.filter_products(db, current_admin)
    tenant_id = tenant_scope.tenant_id_for_row(current_admin)
    # product_id touched in this import (for duplicate rows in same file)
    pending: Dict[str, int] = {}

    for row_num, product_data in enumerate(products_data, start=1):
        try:
            product_name = normalize_product_name(product_data.get("name", ""))
            if not product_name:
                stats["skipped"] += 1
                stats["errors"].append(f"Row {row_num}: Missing product name")
                continue

            product_code = normalize_barcode(str(product_data.get("code", "") or ""))
            category_name = (product_data.get("category") or "").strip()
            avg_cost = product_data.get("cost", Decimal("0.00"))
            selling_price = product_data.get("price", Decimal("0.00"))
            in_hand_stock = max(0.0, float(product_data.get("stock", 0.0)))

            category = None
            if category_name:
                category = get_or_create_category(db, category_name, current_admin)
            category_id = category.id if category else None

            pending_id = _lookup_pending(pending, product_name, product_code)

            if pending_id is not None:
                existing = pq.filter(Product.id == pending_id).first()
                if existing:
                    merge_product_from_import(
                        db,
                        pq,
                        existing,
                        name=product_name,
                        category_id=category_id,
                        avg_cost=avg_cost,
                        selling_price=selling_price,
                        stock_to_add=in_hand_stock,
                        barcode=product_code,
                    )
                    db.commit()
                    stats["merged_rows"] += 1
                    stats["updated"] += 1
                    continue

            existing_product = find_existing_product(pq, product_name, product_code)

            if existing_product:
                merge_product_from_import(
                    db,
                    pq,
                    existing_product,
                    name=product_name,
                    category_id=category_id,
                    avg_cost=avg_cost,
                    selling_price=selling_price,
                    stock_to_add=in_hand_stock,
                    barcode=product_code,
                )
                db.commit()
                _register_pending(pending, existing_product.id, product_name, product_code)
                stats["updated"] += 1
                logger.info(
                    "Import merge: product id=%s name=%r barcode=%r",
                    existing_product.id,
                    product_name,
                    product_code,
                )
                continue

            barcode = product_code
            if barcode:
                conflict = pq.filter(Product.barcode == barcode).first()
                if conflict:
                    stats["errors"].append(
                        f"Row {row_num}: Barcode '{barcode}' already on '{conflict.name}'. "
                        f"Merged by name if possible."
                    )
                    # Try name-only product without this barcode
                    by_name = find_existing_product(pq, product_name, None)
                    if by_name:
                        merge_product_from_import(
                            db,
                            pq,
                            by_name,
                            name=product_name,
                            category_id=category_id,
                            avg_cost=avg_cost,
                            selling_price=selling_price,
                            stock_to_add=in_hand_stock,
                            barcode=None,
                        )
                        db.commit()
                        _register_pending(pending, by_name.id, product_name, product_code)
                        stats["updated"] += 1
                        continue
                    barcode = None

            # Last chance: same name in DB (avoid duplicate POS line)
            again = find_existing_product(pq, product_name, None)
            if again:
                merge_product_from_import(
                    db,
                    pq,
                    again,
                    name=product_name,
                    category_id=category_id,
                    avg_cost=avg_cost,
                    selling_price=selling_price,
                    stock_to_add=in_hand_stock,
                    barcode=product_code if not again.barcode else None,
                )
                db.commit()
                _register_pending(pending, again.id, product_name, product_code)
                stats["updated"] += 1
                continue

            product = Product(
                name=product_name,
                barcode=barcode,
                category_id=category_id,
                stock_qty=max(0.0, in_hand_stock),
                cost_price=avg_cost,
                selling_price=selling_price,
                is_active=True,
                tenant_id=tenant_id,
            )
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
            db.commit()
            db.refresh(product)
            _register_pending(pending, product.id, product_name, product_code)
            stats["created"] += 1
        except Exception as e:
            stats["skipped"] += 1
            stats["errors"].append(f"Row {row_num}: {str(e)}")
            logger.error("Import row %s failed: %s", row_num, e, exc_info=True)
            db.rollback()

    return stats
