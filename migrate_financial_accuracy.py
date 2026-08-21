#!/usr/bin/env python3
"""
Financial accuracy migration (idempotent, PostgreSQL- and SQLite-safe).

Creates / ensures:
  - sale_items.unit_cost
  - store_settings.currency
  - withdrawals.purpose
  - expenses + cash_movements tables (via metadata.create_all)
  - refunds / refund_items if missing (via create_all; see also migrate_refunds.py)
  - backfill unit_cost from products.cost_price
  - backfill purpose from legacy reasons (never invent owner_draw)
  - CoA 1050 / 1450 / 3300 when chart already exists

Usage:
  python3 migrate_financial_accuracy.py              # apply
  python3 migrate_financial_accuracy.py --dry-run    # report only
  python3 migrate_financial_accuracy.py --verify     # exit 1 if checklist fails

Preferred deploy timing: **before** application deploy (manual or Render pre-deploy).
Do not rely solely on app startup create_all for production.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from app.database import engine  # noqa: E402
from app.financial_schema import (  # noqa: E402
    ensure_financial_accuracy_schema,
    verify_financial_schema,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_financial_accuracy")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print verification checklist without mutating schema",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Exit 0 only if all required schema checks pass",
    )
    parser.add_argument(
        "--no-create-tables",
        action="store_true",
        help="Skip Base.metadata.create_all (columns-only mode)",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        checklist = verify_financial_schema(engine)
        for key, ok in checklist.items():
            logger.info("DRY-RUN %s = %s", key, ok)
        missing = [k for k, ok in checklist.items() if not ok]
        if missing:
            logger.warning("Missing before migrate: %s", ", ".join(missing))
            return 2
        logger.info("DRY-RUN: all checklist items already present")
        return 0

    report = ensure_financial_accuracy_schema(
        engine, create_missing_tables=not args.no_create_tables
    )
    logger.info("Migration report: %s", report)

    checklist = verify_financial_schema(engine)
    for key, ok in checklist.items():
        logger.info("VERIFY %s = %s", key, ok)
    missing = [k for k, ok in checklist.items() if not ok]
    if args.verify or missing:
        if missing:
            logger.error("Schema checklist failed: %s", ", ".join(missing))
            return 1
    logger.info("Financial accuracy migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
