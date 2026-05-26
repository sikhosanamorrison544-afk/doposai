#!/usr/bin/env python3
"""Index for fast tenant product counts and paginated admin lists. Idempotent."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402


def migrate() -> None:
    stmts = [
        "CREATE INDEX IF NOT EXISTS ix_products_tenant_active_name "
        "ON products (tenant_id, is_active, name)",
    ]
    with engine.begin() as conn:
        for sql in stmts:
            conn.execute(text(sql))
    print("Product list indexes ready.")


if __name__ == "__main__":
    migrate()
