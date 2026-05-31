"""Tests for CSV inventory import parsing and merge."""
from decimal import Decimal

from app.inventory_csv import (
    EXPORT_HEADERS,
    extract_products_from_csv_bytes,
    import_meta_from_column_map,
    infer_column_map,
    merge_import_rows,
    normalize_match_name,
    parse_decimal,
    products_from_table_rows,
    row_to_product,
)


def test_parse_decimal_currency():
    assert parse_decimal("$1,234.56") == Decimal("1234.56")
    assert parse_decimal("US$ 99.50") == Decimal("99.50")


def test_export_format_round_trip():
    csv_text = (
        "ID,Name,Barcode,Category,Stock Qty,Cost Price,Selling Price,Is Active\n"
        ",Widget A,123,Tools,5,$10.50,$19.99,Yes\n"
    )
    products = extract_products_from_csv_bytes(csv_text.encode("utf-8"))
    assert len(products) == 1
    p = products[0]
    assert p["name"] == "Widget A"
    assert p["cost"] == Decimal("10.50")
    assert p["price"] == Decimal("19.99")
    assert p["stock"] == 5.0
    assert p.get("stock_mode") == "set"


def test_jumbled_column_order():
    csv_text = (
        "Selling Price,Item Description,Qty on Hand,Buy Price,SKU\n"
        "$6.00,Orange Juice,24,$3.00,SKU-99\n"
    )
    products = extract_products_from_csv_bytes(csv_text.encode("utf-8"))
    assert len(products) == 1
    assert products[0]["name"] == "Orange Juice"
    assert products[0]["cost"] == Decimal("3.00")
    assert products[0]["price"] == Decimal("6.00")
    assert products[0]["stock"] == 24.0
    assert products[0]["code"] == "SKU-99"


def test_merge_duplicate_rows_in_file():
    rows = [
        {
            "name": "Bolt",
            "code": "B1",
            "cost": Decimal("1"),
            "price": Decimal("2"),
            "stock": 5.0,
            "has_stock": True,
            "stock_mode": "add",
        },
        {
            "name": "Bolt",
            "code": "B1",
            "cost": Decimal("1"),
            "price": Decimal("2"),
            "stock": 3.0,
            "has_stock": True,
            "stock_mode": "add",
        },
    ]
    merged, count = merge_import_rows(rows)
    assert count == 1
    assert len(merged) == 1
    assert merged[0]["stock"] == 8.0


def test_infer_column_map_reordered():
    headers = ["Retail", "Description", "On Hand", "Purchase", "EAN"]
    cmap = infer_column_map(headers)
    assert cmap.col("name") == "Description"
    assert cmap.col("price") == "Retail"
    assert cmap.col("cost") == "Purchase"
    assert cmap.col("stock") == "On Hand"
    assert cmap.col("code") == "EAN"


def test_legacy_headers():
    row = {
        "Product name": "Tea",
        "Product code": "9988",
        "Average cost": "$2.00",
        "Selling price": "$4.50",
        "In hand stock": "12",
    }
    p = row_to_product(row)
    assert p is not None
    assert p["cost"] == Decimal("2.00")
    assert p["price"] == Decimal("4.50")


def test_export_headers_stable():
    assert "ID" in EXPORT_HEADERS
    assert "Stock Qty" in EXPORT_HEADERS


def test_normalize_match_name_dedupes_punctuation():
    assert normalize_match_name("Widget-A") == normalize_match_name("Widget A")
    assert normalize_match_name("  BOLT  ") == normalize_match_name("bolt")


def test_merge_same_name_different_punctuation_in_file():
    rows = [
        {
            "name": "Cola-500ml",
            "code": "",
            "cost": Decimal("1"),
            "price": Decimal("2"),
            "stock": 5.0,
            "has_stock": True,
            "stock_mode": "add",
        },
        {
            "name": "Cola 500ml",
            "code": "",
            "cost": Decimal("1"),
            "price": Decimal("2"),
            "stock": 3.0,
            "has_stock": True,
            "stock_mode": "add",
        },
    ]
    merged, count = merge_import_rows(rows)
    assert count == 1
    assert len(merged) == 1
    assert merged[0]["stock"] == 8.0


def test_line_number_column_not_treated_as_product_id():
    csv_text = (
        "No,Product name,Product code,Selling price,In hand stock\n"
        "1,Alpha,AAA,1.00,1\n"
        "2,Beta,BBB,2.00,2\n"
    )
    products = extract_products_from_csv_bytes(csv_text.encode("utf-8"))
    assert len(products) == 2
    assert not products[0].get("has_product_id")
    assert products[0].get("product_id") is None
    cmap = infer_column_map(["No", "Product name", "Product code", "Selling price", "In hand stock"])
    assert cmap.col("id") is None


def test_export_id_column_still_maps():
    csv_text = "ID,Name,Barcode,Stock Qty,Selling Price,Cost Price\n,New Item,99,1,5.00,2.00\n"
    products = extract_products_from_csv_bytes(csv_text.encode("utf-8"))
    assert len(products) == 1
    assert not products[0].get("has_product_id")


def test_large_csv_stream_merge():
    lines = ["Name,Barcode,Stock Qty,Selling Price,Cost Price\n"]
    for i in range(500):
        lines.append(f"Product {i},SKU{i},{i % 10},10.00,5.00\n")
    lines.append("Product 1,SKU1,3,10.00,5.00\n")
    products = extract_products_from_csv_bytes("".join(lines).encode("utf-8"))
    merged, _ = merge_import_rows(products)
    assert len(merged) == 500
    p1 = next(p for p in merged if p["name"] == "Product 1")
    assert p1["stock"] == 3.0


def test_mrp_and_rate_price_headers():
    csv_text = (
        "Item Description,MRP,Qty,Buy Price\n"
        "Soap Bar,12.50,10,6.00\n"
    )
    products = extract_products_from_csv_bytes(csv_text.encode("utf-8"))
    assert len(products) == 1
    assert products[0]["price"] == Decimal("12.50")
    assert products[0]["cost"] == Decimal("6.00")
    assert products[0]["has_price"] is True
    assert products[0]["has_cost"] is True


def test_table_rows_set_price_flags():
    headers = ["Product", "Rate", "On Hand"]
    rows = [["Bread", "5.99", "20"]]
    products = products_from_table_rows(headers, rows)
    assert len(products) == 1
    assert products[0]["price"] == Decimal("5.99")
    assert products[0]["has_price"] is True
    assert products[0]["stock"] == 20.0
    assert products[0]["has_stock"] is True


def test_import_meta_warns_when_price_missing():
    meta = import_meta_from_column_map(infer_column_map(["Name", "Qty"]))
    assert meta["price_column_detected"] is False
    assert any("selling price" in w.lower() for w in meta["warnings"])
