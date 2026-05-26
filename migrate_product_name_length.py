#!/usr/bin/env python3
"""Widen products.name to VARCHAR(255) (idempotent). Run: python3 migrate_product_name_length.py"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def migrate():
    from sqlalchemy import inspect, text

    from app.database import engine

    insp = inspect(engine)
    if "products" not in insp.get_table_names():
        print("products table not found — skip name length migration")
        return

    dialect = engine.dialect.name
    if dialect == "postgresql":
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE products "
                    "ALTER COLUMN name TYPE VARCHAR(255)"
                )
            )
        print("products.name widened to VARCHAR(255) (postgresql)")
    elif dialect == "sqlite":
        print("SQLite: products.name length unchanged (import truncates names)")
    else:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE products MODIFY COLUMN name VARCHAR(255)")
            )
        print("products.name widened to VARCHAR(255)")


if __name__ == "__main__":
    migrate()
