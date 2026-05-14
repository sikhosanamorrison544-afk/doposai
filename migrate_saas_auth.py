#!/usr/bin/env python3
"""
SQLite migration: SaaS multi-tenant columns, refresh_tokens, password_reset_tokens,
and tenants.tenant_uid / subscription fields.
Run: python3 migrate_saas_auth.py
"""
import sqlite3
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "pos.db"


def column_names(conn: sqlite3.Connection, table: str) -> set:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def migrate():
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}")
        return
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cols = column_names(conn, "tenants")
        if "tenant_uid" not in cols:
            print("Adding tenants SaaS columns...")
            conn.execute("ALTER TABLE tenants ADD COLUMN tenant_uid VARCHAR(36)")
            conn.execute("ALTER TABLE tenants ADD COLUMN owner_name VARCHAR(120)")
            conn.execute(
                "ALTER TABLE tenants ADD COLUMN subscription_status VARCHAR(32) DEFAULT 'trial'"
            )
            conn.execute("ALTER TABLE tenants ADD COLUMN trial_ends_at DATETIME")
            conn.execute("ALTER TABLE tenants ADD COLUMN last_subscription_verified_at DATETIME")
            conn.execute("ALTER TABLE tenants ADD COLUMN firestore_doc_id VARCHAR(128)")
            for row in conn.execute("SELECT id FROM tenants").fetchall():
                uid = str(uuid.uuid4())
                conn.execute("UPDATE tenants SET tenant_uid = ? WHERE id = ?", (uid, row[0]))
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_tenant_uid ON tenants(tenant_uid)"
            )
        ucols = column_names(conn, "users")
        if "tenant_id" not in ucols:
            print("Adding users.tenant_id and users.email...")
            conn.execute("ALTER TABLE users ADD COLUMN email VARCHAR(120)")
            conn.execute("ALTER TABLE users ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_users_email ON users(email)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users(tenant_id)")

        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='refresh_tokens'"
        )
        if cur.fetchone() is None:
            print("Creating refresh_tokens...")
            conn.execute(
                """
                CREATE TABLE refresh_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash VARCHAR(64) NOT NULL UNIQUE,
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    revoked_at DATETIME
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS ix_refresh_user ON refresh_tokens(user_id)")
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='password_reset_tokens'"
        )
        if cur.fetchone() is None:
            print("Creating password_reset_tokens...")
            conn.execute(
                """
                CREATE TABLE password_reset_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash VARCHAR(64) NOT NULL UNIQUE,
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    used_at DATETIME
                )
                """
            )
        conn.commit()
        print("Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
