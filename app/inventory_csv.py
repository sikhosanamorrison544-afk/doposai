"""Shared CSV inventory import/export (flexible columns, merge, round-trip)."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

# Standard export columns — import recognizes these in any order.
EXPORT_HEADERS: List[str] = [
    "ID",
    "Name",
    "Barcode",
    "Category",
    "Stock Qty",
    "Cost Price",
    "Selling Price",
    "Is Active",
]

_NON_NUMERIC_RE = re.compile(r"[^\d.,+\-]")

# Minimum fuzzy score to assign a column to a field (0–100 scale).
_MIN_COLUMN_SCORE = 12.0

_FIELD_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "id": (
        "productid",
        "itemid",
        "id",
        "no",
        "num",
    ),
    "name": (
        "productname",
        "itemname",
        "description",
        "product",
        "item",
        "name",
        "title",
        "merchandise",
        "article",
    ),
    "code": (
        "barcode",
        "productcode",
        "sku",
        "upc",
        "ean",
        "plu",
        "code",
        "ref",
        "reference",
    ),
    "category": (
        "productcategory",
        "subcategory",
        "department",
        "category",
        "group",
        "type",
        "class",
    ),
    "cost": (
        "averagecost",
        "costprice",
        "buyingprice",
        "purchaseprice",
        "buyprice",
        "unitcost",
        "landedcost",
        "wholesale",
        "cost",
        "buying",
        "purchase",
        "cogs",
    ),
    "price": (
        "sellingprice",
        "saleprice",
        "salesprice",
        "retailprice",
        "unitprice",
        "sellprice",
        "selling",
        "retail",
        "price",
        "rsp",
        "srp",
    ),
    "stock": (
        "inhandstock",
        "stockqty",
        "stockquantity",
        "quantityonhand",
        "onhand",
        "instock",
        "openingstock",
        "currentstock",
        "balance",
        "stock",
        "quantity",
        "qty",
        "units",
    ),
}

# Headers implying stock column is an absolute on-hand count (export round-trip, stock take).
_STOCK_SET_HINTS = frozenset(
    {
        "stockqty",
        "stockquantity",
        "inhandstock",
        "quantityonhand",
        "onhand",
        "instock",
        "currentstock",
        "openingstock",
        "balance",
        "closingstock",
    }
)

# Headers implying stock should be added to existing (deliveries, receipts).
_STOCK_ADD_HINTS = frozenset(
    {
        "qtyreceived",
        "quantityreceived",
        "received",
        "added",
        "addqty",
        "adjustment",
        "delta",
        "incoming",
    }
)


def _norm_key(key: str) -> str:
    return "".join(ch for ch in (key or "").strip().lower() if ch.isalnum())


_SKIP_AS_NAME = frozenset(
    {
        _norm_key(x)
        for x in (
            "id",
            "is active",
            "active",
            "last updated",
            "updated",
            "status",
            "notes",
            "remark",
        )
    }
)

# Exact normalized header -> field (longer phrases win in fuzzy pass too)
_HEADER_TO_FIELD: Dict[str, str] = {}
for _field, _labels in {
    "id": ("id", "product id", "item id", "productid"),
    "name": ("product name", "item name", "product description", "description", "product", "item", "name"),
    "code": ("product code", "product barcode", "barcode", "sku", "upc", "ean", "code"),
    "category": ("product category", "product sub category", "sub category", "category", "cat"),
    "cost": (
        "average cost",
        "cost price",
        "buying price",
        "purchase price",
        "buy price",
        "unit cost",
        "landed cost",
        "wholesale price",
        "cost",
        "buying",
        "purchase",
    ),
    "price": (
        "selling price",
        "sale price",
        "sales price",
        "retail price",
        "unit price",
        "sell price",
        "rsp",
        "srp",
        "price",
        "selling",
    ),
    "stock": (
        "in hand stock",
        "stock qty",
        "stock quantity",
        "quantity on hand",
        "on hand",
        "in stock",
        "stock",
        "quantity",
        "qty",
    ),
}.items():
    for _label in _labels:
        _HEADER_TO_FIELD[_norm_key(_label)] = _field


def _normalize_number_string(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    s = _NON_NUMERIC_RE.sub("", s)
    if not s or s in ("+", "-", ".", ",", "+.", "-."):
        return ""
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = parts[0].replace(".", "") + "." + parts[1]
        else:
            s = s.replace(",", "")
    return s


def parse_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0.00")
    raw = str(value).strip()
    if not raw:
        return Decimal("0.00")
    s = _normalize_number_string(raw)
    if not s:
        return Decimal("0.00")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def parse_float(value: Any) -> float:
    if value is None:
        return 0.0
    raw = str(value).strip()
    if not raw:
        return 0.0
    s = _normalize_number_string(raw)
    if not s:
        return 0.0
    try:
        return max(0.0, float(s))
    except (ValueError, TypeError):
        return 0.0


def normalize_product_name(name: str) -> str:
    return " ".join((name or "").strip().split())


def normalize_match_name(name: str) -> str:
    """Normalized key for duplicate detection (case/punctuation/spacing insensitive)."""
    n = normalize_product_name(name).lower()
    if not n:
        return ""
    n = re.sub(r"[^\w]", "", n, flags=re.UNICODE)
    return n


def normalize_barcode_for_match(code: str) -> Optional[str]:
    """Normalize barcode/SKU for matching (Excel scientific notation, trim)."""
    c = (code or "").strip()
    if not c:
        return None
    if re.match(r"^\d+\.?\d*[eE][+\-]?\d+$", c):
        try:
            c = str(int(float(c)))
        except (ValueError, OverflowError):
            pass
    return c


@dataclass
class ColumnMap:
    """Maps logical import fields to actual CSV column headers."""

    columns: Dict[str, Optional[str]] = field(default_factory=dict)
    stock_mode: str = "add"  # "add" = sum into existing; "set" = replace on-hand qty

    def col(self, field: str) -> Optional[str]:
        return self.columns.get(field)

    def as_display_dict(self) -> Dict[str, Optional[str]]:
        return {k: v for k, v in self.columns.items()}


def _score_header_for_field(header: str, field: str) -> float:
    nk = _norm_key(header)
    if not nk:
        return 0.0
    if field == "name" and nk in _SKIP_AS_NAME:
        return 0.0
    if field == "id" and nk in _SKIP_AS_NAME and nk != "id":
        return 0.0

    if _HEADER_TO_FIELD.get(nk) == field:
        return 100.0

  # Penalize ambiguous "price" matching cost field
    if field == "cost" and any(x in nk for x in ("sell", "sale", "retail", "rsp", "srp")):
        return 0.0
    if field == "price" and any(x in nk for x in ("cost", "buy", "purchase", "cogs", "wholesale")):
        if not any(x in nk for x in ("sell", "sale", "retail", "rsp", "srp")):
            return 0.0

    score = 0.0
    for kw in _FIELD_KEYWORDS.get(field, ()):
        if kw == nk:
            score = max(score, 85.0)
        elif nk.startswith(kw) or nk.endswith(kw):
            score = max(score, 55.0)
        elif kw in nk and len(kw) >= 4:
            score = max(score, 40.0 + min(len(kw), 10))

    # Single-word fallbacks
    if field == "name" and nk in ("name", "product", "item", "description"):
        score = max(score, 50.0)
    if field == "stock" and nk in ("qty", "quantity", "stock"):
        score = max(score, 45.0)

    return score


def infer_column_map(fieldnames: List[str]) -> ColumnMap:
    """Pick the best CSV column for each logical field (order-independent)."""
    clean_fields = [f for f in fieldnames if f and str(f).strip()]
    if not clean_fields:
        return ColumnMap()

    scores: Dict[Tuple[str, str], float] = {}
    for col in clean_fields:
        for fld in _FIELD_KEYWORDS:
            scores[(fld, col)] = _score_header_for_field(col, fld)

    # Assign greedily: highest scores first, each column used once.
    assigned: Dict[str, Optional[str]] = {f: None for f in _FIELD_KEYWORDS}
    used: set = set()
    pairs = sorted(
        ((scores.get((fld, col), 0.0), fld, col) for fld in _FIELD_KEYWORDS for col in clean_fields),
        reverse=True,
    )
    for sc, fld, col in pairs:
        if sc < _MIN_COLUMN_SCORE:
            break
        if assigned.get(fld) is not None or col in used:
            continue
        assigned[fld] = col
        used.add(col)

    stock_col = assigned.get("stock")
    stock_mode = "add"
    if stock_col:
        sn = _norm_key(stock_col)
        if sn in _STOCK_SET_HINTS or any(h in sn for h in _STOCK_SET_HINTS):
            stock_mode = "set"
        elif sn in _STOCK_ADD_HINTS or any(h in sn for h in _STOCK_ADD_HINTS):
            stock_mode = "add"
        elif "hand" in sn or "balance" in sn or sn.endswith("qty"):
            stock_mode = "set"

    return ColumnMap(columns=assigned, stock_mode=stock_mode)


def _cell(row: Dict[str, Any], col: Optional[str]) -> str:
    if not col:
        return ""
    val = row.get(col)
    if val is None:
        return ""
    return str(val).strip()


def row_to_product(row: Dict[str, Any], column_map: Optional[ColumnMap] = None) -> Optional[Dict[str, Any]]:
    cmap = column_map or infer_column_map(list(row.keys()))

    name = _cell(row, cmap.col("name"))
    code = _cell(row, cmap.col("code"))
    category = _cell(row, cmap.col("category"))
    id_raw = _cell(row, cmap.col("id"))
    cost_raw = _cell(row, cmap.col("cost"))
    price_raw = _cell(row, cmap.col("price"))
    stock_raw = _cell(row, cmap.col("stock"))

    product_id: Optional[int] = None
    if id_raw:
        try:
            product_id = int(float(id_raw))
        except (ValueError, TypeError):
            product_id = None

    if not name and code:
        name = code
    if not name and not code:
        return None

    cost = parse_decimal(cost_raw) if cost_raw else Decimal("0.00")
    price = parse_decimal(price_raw) if price_raw else Decimal("0.00")
    stock = parse_float(stock_raw) if stock_raw else 0.0

    return {
        "product_id": product_id,
        "name": name,
        "code": code,
        "category": category,
        "cost": cost,
        "price": price,
        "stock": stock,
        "has_cost": bool(cost_raw),
        "has_price": bool(price_raw),
        "has_stock": bool(stock_raw),
        "stock_mode": cmap.stock_mode,
    }


def _dedupe_key(product: Dict[str, Any]) -> str:
    pid = product.get("product_id")
    if pid is not None:
        return f"id:{pid}"
    code = normalize_barcode_for_match(str(product.get("code") or ""))
    if code:
        return f"b:{code.lower()}"
    match_name = normalize_match_name(str(product.get("name") or ""))
    if match_name:
        return f"n:{match_name}"
    return "n:"


def _merge_two_products(accum: Dict[str, Any], row: Dict[str, Any]) -> None:
    """Merge a duplicate row from the same file into accum."""
    mode = row.get("stock_mode") or accum.get("stock_mode") or "add"
    if row.get("has_stock"):
        if mode == "set":
            accum["stock"] = float(row.get("stock", 0.0))
        else:
            accum["stock"] = float(accum.get("stock", 0.0)) + float(row.get("stock", 0.0))
        accum["has_stock"] = True

    for flag in ("has_cost", "has_price"):
        if row.get(flag):
            accum[flag] = True
            if flag == "has_cost":
                accum["cost"] = row.get("cost", accum.get("cost"))
            if flag == "has_price":
                accum["price"] = row.get("price", accum.get("price"))

    if row.get("category") and not accum.get("category"):
        accum["category"] = row["category"]
    if row.get("code") and not accum.get("code"):
        accum["code"] = row["code"]
    if row.get("product_id") is not None:
        accum["product_id"] = row["product_id"]
    # Prefer longer / more descriptive name
    if len((row.get("name") or "")) > len((accum.get("name") or "")):
        accum["name"] = row["name"]


def merge_import_rows(products: List[dict]) -> Tuple[List[dict], int]:
    """
    Merge duplicate lines within one file (same barcode or same product name).
    Returns (merged_products, number_of_rows_combined).
    """
    merged_count = 0
    by_key: Dict[str, dict] = {}
    order: List[str] = []

    for p in products:
        key = _dedupe_key(p)
        if key in by_key:
            _merge_two_products(by_key[key], p)
            merged_count += 1
        else:
            by_key[key] = dict(p)
            order.append(key)

    return [by_key[k] for k in order], merged_count


def _decode_csv_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _detect_csv_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample[:8192], delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def _header_likelihood(cells: List[str]) -> float:
    """Score how likely a row is a header (not data)."""
    if not cells:
        return 0.0
    cmap = infer_column_map(cells)
    score = 0.0
    if cmap.col("name"):
        score += 40
    if cmap.col("stock"):
        score += 20
    if cmap.col("price") or cmap.col("cost"):
        score += 20
    if cmap.col("code"):
        score += 10
    # Headers are usually mostly non-numeric
    numeric = 0
    for c in cells:
        s = str(c or "").strip()
        if s and _normalize_number_string(s) == s.replace(" ", ""):
            try:
                float(_normalize_number_string(s))
                numeric += 1
            except ValueError:
                pass
    if cells and numeric / len(cells) > 0.6:
        score -= 30
    return score


def _find_header_row(lines: List[str], dialect: csv.Dialect) -> int:
    best_idx = 0
    best_score = -1.0
    for idx in range(min(20, len(lines))):
        line = lines[idx].strip()
        if not line:
            continue
        try:
            cells = next(csv.reader([line], dialect=dialect))
        except csv.Error:
            continue
        sc = _header_likelihood(cells)
        if sc > best_score:
            best_score = sc
            best_idx = idx
    return best_idx


def parse_csv_import_meta(content: bytes) -> Dict[str, Any]:
    """Return detected column mapping and stock mode for a CSV (for API feedback)."""
    content_str = _decode_csv_text(content)
    if not content_str.strip():
        return {"columns_mapped": {}, "stock_mode": "add"}
    dialect = _detect_csv_dialect(content_str)
    lines = content_str.splitlines()
    header_idx = _find_header_row(lines, dialect)
    body = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(body), dialect=dialect)
    fieldnames = list(reader.fieldnames or [])
    cmap = infer_column_map(fieldnames)
    display = {f: cmap.col(f) for f in ("id", "name", "code", "category", "stock", "cost", "price")}
    return {"columns_mapped": display, "stock_mode": cmap.stock_mode}


def iter_products_from_csv_bytes(content: bytes):
    """
    Stream-parse CSV rows into product dicts (memory-efficient for large files).
    Yields one product dict per valid data row.
    """
    content_str = _decode_csv_text(content)
    if not content_str.strip():
        return

    dialect = _detect_csv_dialect(content_str)
    lines = content_str.splitlines()
    header_idx = _find_header_row(lines, dialect)
    body = "\n".join(lines[header_idx:])
    if not body.strip():
        return

    reader = csv.DictReader(io.StringIO(body), dialect=dialect)
    fieldnames = list(reader.fieldnames or [])
    if not fieldnames:
        return

    column_map = infer_column_map(fieldnames)
    for row in reader:
        if not row:
            continue
        if not any(str(v or "").strip() for v in row.values()):
            continue
        product = row_to_product(row, column_map)
        if product:
            yield product


def extract_products_from_csv_bytes(content: bytes) -> List[dict]:
    """Parse CSV bytes; merge duplicate lines in-file before DB import."""
    raw = list(iter_products_from_csv_bytes(content))
    if not raw:
        return []
    merged, _ = merge_import_rows(raw)
    return merged


def build_products_csv_bytes(rows: List[List[Any]]) -> bytes:
    """Build UTF-8 CSV with BOM for Excel download."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EXPORT_HEADERS)
    for row in rows:
        writer.writerow(row)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def product_to_export_row(product: Any) -> List[Any]:
    """Convert a Product ORM row to an export CSV line."""
    category_name = product.category.name if getattr(product, "category", None) else ""
    return [
        product.id,
        product.name,
        product.barcode or "",
        category_name,
        float(product.stock_qty or 0),
        float(product.cost_price or 0),
        float(product.selling_price or 0),
        "Yes" if product.is_active else "No",
    ]
