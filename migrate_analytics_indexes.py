#!/usr/bin/env python3
"""Indexes for analytics date-range queries. Idempotent. Run on deploy."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402


def migrate() -> None:
    stmts = [
        "CREATE INDEX IF NOT EXISTS ix_sale_items_product_id ON sale_items (product_id)",
        "CREATE INDEX IF NOT EXISTS ix_sales_tenant_created ON sales (tenant_id, created_at)",
    ]
    with engine.begin() as conn:
        for sql in stmts:
            conn.execute(text(sql))
    print("Analytics indexes ready.")


if __name__ == "__main__":
    migrate()
