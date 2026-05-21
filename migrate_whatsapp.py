#!/usr/bin/env python3
"""WhatsApp chatbot schema migration (SQLite + PostgreSQL).

Idempotent. Safe to run on every deploy:
  - Creates whatsapp_sessions, whatsapp_chatbot_messages via SQLAlchemy create_all.
    (We deliberately avoid the table name 'whatsapp_messages' because some
     legacy deployments already have a table with that name and a different
     schema; see app/whatsapp/models.py for the rationale.)
  - Adds new tenant columns (whatsapp_*, business_*, logo_url) via ALTER
    TABLE ... ADD COLUMN IF NOT EXISTS on Postgres, or PRAGMA check on
    SQLite.

Run: python3 migrate_whatsapp.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from app.config import DATABASE_URL  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app import models  # noqa: F401, E402
from app import enterprise_models  # noqa: F401, E402
from app import accounting_models  # noqa: F401, E402
from app.quotation_models import Tenant  # noqa: F401, E402
from app.whatsapp import models as _wa_models  # noqa: F401, E402


_TENANT_COLUMN_ADDS = [
    ("business_type", "VARCHAR(64)"),
    ("business_description", "TEXT"),
    ("logo_url", "VARCHAR(500)"),
    ("whatsapp_enabled", "BOOLEAN DEFAULT FALSE"),
    ("whatsapp_keyword", "VARCHAR(32)"),
    ("whatsapp_welcome_message", "TEXT"),
]


def _sqlite_alter(conn, table: str, col: str, ddl: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in cur.fetchall()}
    if col not in cols:
        # SQLite doesn't support IF NOT EXISTS on ADD COLUMN; we just checked.
        print(f"  ALTER {table} ADD {col}")
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def migrate_sqlite() -> None:
    import sqlite3

    db_path = BASE / "pos.db"
    if not db_path.exists():
        print("No pos.db — create_all will run on first app start.")
        return
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tenants'"
        )
        if cur.fetchone() is None:
            print("tenants table missing — run prior migrations first.")
            return
        for col, ddl in _TENANT_COLUMN_ADDS:
            _sqlite_alter(conn, "tenants", col, ddl)
        # SQLite can't add a UNIQUE constraint via ALTER, so create a partial index.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "ux_tenants_whatsapp_keyword ON tenants(whatsapp_keyword) "
            "WHERE whatsapp_keyword IS NOT NULL"
        )
        conn.commit()
    finally:
        conn.close()


def migrate_postgres() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        return
    from sqlalchemy import text

    with engine.connect() as conn:
        for col, ddl in _TENANT_COLUMN_ADDS:
            stmt = f"ALTER TABLE tenants ADD COLUMN IF NOT EXISTS {col} {ddl}"
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"  OK: {stmt[:80]}")
            except Exception as exc:  # noqa: BLE001 — log and continue
                print(f"  SKIP ({col}): {exc}")
        try:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ux_tenants_whatsapp_keyword "
                    "ON tenants (whatsapp_keyword) "
                    "WHERE whatsapp_keyword IS NOT NULL"
                )
            )
            conn.commit()
            print("  OK: ux_tenants_whatsapp_keyword")
        except Exception as exc:  # noqa: BLE001
            print(f"  SKIP (keyword index): {exc}")


def main() -> None:
    print("Creating WhatsApp tables via SQLAlchemy metadata...")
    Base.metadata.create_all(bind=engine)
    print("Done create_all.")
    if DATABASE_URL.startswith("sqlite"):
        migrate_sqlite()
    else:
        migrate_postgres()
    print("WhatsApp migration complete.")


if __name__ == "__main__":
    main()
