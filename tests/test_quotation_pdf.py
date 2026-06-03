"""Tests for quotation PDF layout helpers."""
from app.quotation_service import _short_product_label


def test_short_product_label_truncates_long_names():
    long_name = "80a 12/24/36/48v Mppt controller 7091 extra"
    short = _short_product_label(long_name)
    assert len(short) <= 22
    assert short.endswith("…")


def test_short_product_label_keeps_short_names():
    assert _short_product_label("Cable 2m") == "Cable 2m"


def test_short_product_label_empty():
    assert _short_product_label("") == "—"
