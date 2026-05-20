#!/usr/bin/env python3
"""
Enterprise schema migration (SQLite + PostgreSQL via SQLAlchemy create_all for new tables).

Run: python3 migrate_enterprise.py

Also adds optional branch_id to users, sales, cashier_shifts when missing.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from app.config import DATABASE_URL  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app import models  # noqa: F401, E402
from app import enterprise_models  # noqa: F401, E402
from app.quotation_models import Tenant  # noqa: F401, E402
from app import accounting_models  # noqa: F401, E402


def _sqlite_alter(conn, table: str, col: str, ddl: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in cur.fetchall()}
    if col not in cols:
        print(f"  ALTER {table} ADD {col}")
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def migrate_sqlite():
    import sqlite3

    db_path = BASE / "pos.db"
    if not db_path.exists():
        print("No pos.db — create_all will run on first app start.")
        return
    conn = sqlite3.connect(str(db_path))
    try:
        # branches table must exist before branch_id FK columns
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='branches'"
        )
        if cur.fetchone() is None:
            print("Run create_all first (branches table missing).")
            return
        for table, col, ddl in [
            ("users", "branch_id", "branch_id INTEGER"),
            ("sales", "branch_id", "branch_id INTEGER"),
            ("cashier_shifts", "branch_id", "branch_id INTEGER"),
        ]:
            _sqlite_alter(conn, table, col, ddl)
        conn.commit()
    finally:
        conn.close()


def migrate_postgres_optional():
    if not DATABASE_URL.startswith("postgresql"):
        return
    from sqlalchemy import text

    with engine.connect() as conn:
        for stmt in [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id)",
            "ALTER TABLE sales ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id)",
            "ALTER TABLE cashier_shifts ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id)",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"  OK: {stmt[:60]}...")
            except Exception as e:
                print(f"  Skip (may need branches table first): {e}")


def main():
    print("Creating enterprise tables via SQLAlchemy metadata...")
    Base.metadata.create_all(bind=engine)
    print("Done create_all.")
    if DATABASE_URL.startswith("sqlite"):
        migrate_sqlite()
    else:
        migrate_postgres_optional()
    print("Enterprise migration complete.")


if __name__ == "__main__":
    main()
