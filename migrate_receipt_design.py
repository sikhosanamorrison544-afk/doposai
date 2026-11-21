#!/usr/bin/env python3
"""
Idempotent migration: Receipt Design columns on store_settings.

Adds:
  - receipt_keep_for_refund_text
  - receipt_footer
  - receipt_phone_1
  - receipt_phone_2
  - receipt_phone_3

Safe on PostgreSQL and SQLite. Run via Render start or manually:
  python3 migrate_receipt_design.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from sqlalchemy import inspect  # noqa: E402

from app.database import engine  # noqa: E402
from app.financial_schema import add_column_if_missing, columns  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_receipt_design")

RECEIPT_COLUMNS = (
    ("receipt_keep_for_refund_text", "VARCHAR(200)"),
    ("receipt_footer", "TEXT"),
    ("receipt_phone_1", "VARCHAR(32)"),
    ("receipt_phone_2", "VARCHAR(32)"),
    ("receipt_phone_3", "VARCHAR(32)"),
)


def ensure_receipt_design_schema(eng=None) -> dict:
    eng = eng or engine
    report = {"added": [], "skipped": []}
    if "store_settings" not in inspect(eng).get_table_names():
        logger.warning("store_settings table missing — skip receipt design columns")
        return report
    existing = columns(eng, "store_settings")
    with eng.begin() as conn:
        for col, ddl in RECEIPT_COLUMNS:
            if add_column_if_missing(conn, "store_settings", col, ddl, existing=existing):
                report["added"].append(col)
                existing.add(col)
            else:
                report["skipped"].append(col)
    return report


def main() -> int:
    report = ensure_receipt_design_schema(engine)
    logger.info("Receipt design migration: %s", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
