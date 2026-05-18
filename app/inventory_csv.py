"""Shared CSV inventory import parsing (export + legacy column names)."""
from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional


def parse_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0.00")
    s = str(value).strip()
    if not s:
        return Decimal("0.00")
    try:
        return Decimal(s.replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def parse_float(value: Any) -> float:
    if value is None:
        return 0.0
    s = str(value).strip()
    if not s:
        return 0.0
    try:
        return max(0.0, float(s.replace(",", "")))
    except (ValueError, TypeError):
        return 0.0


def _norm_key(key: str) -> str:
    return "".join(ch for ch in (key or "").strip().lower() if ch.isalnum())


# Maps normalized header -> field name
_HEADER_TO_FIELD: Dict[str, str] = {}
for field, labels in {
    "name": (
        "product name",
        "name",
        "product",
        "item",
        "item name",
        "description",
    ),
    "code": (
        "product code",
        "barcode",
        "code",
        "sku",
        "product barcode",
    ),
    "category": (
        "product category",
        "category",
        "cat",
    ),
    "cost": (
        "average cost",
        "cost price",
        "cost",
        "unit cost",
        "buying price",
    ),
    "price": (
        "selling price",
        "price",
        "sell price",
        "unit price",
        "retail price",
    ),
    "stock": (
        "in hand stock",
        "stock qty",
        "stock",
        "quantity",
        "qty",
        "on hand",
        "in stock",
    ),
}.items():
    for label in labels:
        _HEADER_TO_FIELD[_norm_key(label)] = field


def _row_get(row: Dict[str, Any], field: str) -> str:
    """Read a logical field from a CSV row using flexible header names."""
    for raw_key, raw_val in row.items():
        if _HEADER_TO_FIELD.get(_norm_key(raw_key)) == field:
            return "" if raw_val is None else str(raw_val).strip()
    return ""


def row_to_product(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = _row_get(row, "name")
    code = _row_get(row, "code")
    category = _row_get(row, "category")
    cost = parse_decimal(_row_get(row, "cost") or "0")
    price = parse_decimal(_row_get(row, "price") or "0")
    stock = parse_float(_row_get(row, "stock") or "0")

    if not name and not code and not category:
        return None
    if not name:
        return None

    return {
        "name": name,
        "code": code,
        "category": category,
        "cost": cost,
        "price": price,
        "stock": stock,
    }


def extract_products_from_csv_bytes(content: bytes) -> List[dict]:
    """Parse CSV bytes into product dicts for inventory import."""
    products: List[dict] = []
    try:
        content_str = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        content_str = content.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(content_str))
    if not reader.fieldnames:
        return products

    for row in reader:
        if not row:
            continue
        product = row_to_product(row)
        if product:
            products.append(product)
    return products
