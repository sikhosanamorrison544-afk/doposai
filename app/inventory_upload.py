"""Parse inventory upload bytes (shared by HTTP handler and background import jobs)."""
from __future__ import annotations

from typing import Tuple


def parse_inventory_upload(content: bytes, file_ext: str) -> Tuple[list, dict]:
    """Parse uploaded inventory file into product row dicts."""
    import_meta: dict = {}
    ext = (file_ext or "").lower()
    if ext == ".csv":
        from .inventory_csv import extract_products_from_csv_bytes, parse_csv_import_meta

        return extract_products_from_csv_bytes(content), parse_csv_import_meta(content)
    if ext == ".pdf":
        from .main import extract_products_from_pdf

        return extract_products_from_pdf(content), import_meta
    if ext in (".doc", ".docx"):
        from .main import extract_products_from_word

        return extract_products_from_word(content), import_meta
    raise ValueError(
        f"Unsupported file type: {ext}. Supported: .csv, .pdf, .doc, .docx"
    )
