#!/usr/bin/env python3
"""
Add tenant_id to POS tables for API isolation (legacy rows keep tenant_id NULL).

Run from repo root: python3 migrate_tenant_isolation.py

Default DB path matches migrate_saas_auth.py (pos/pos.db under project).
"""
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "pos.db"


def column_names(conn: sqlite3.Connection, table: str) -> set:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def add_column_if_missing(conn: sqlite3.Connection, table: str, ddl: str) -> None:
    cols = column_names(conn, table)
    if "tenant_id" in cols:
        return
    print(f"Adding {table}.tenant_id ...")
    conn.execute(ddl)


def migrate_categories_table(conn: sqlite3.Connection) -> None:
    cols = column_names(conn, "categories")
    if "tenant_id" in cols:
        return
    print("Rebuilding categories for composite (tenant_id, name) uniqueness ...")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        """
        CREATE TABLE categories__new (
            id INTEGER NOT NULL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id),
            name VARCHAR(80) NOT NULL,
            description TEXT,
            UNIQUE (tenant_id, name)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO categories__new (id, tenant_id, name, description)
        SELECT id, NULL, name, description FROM categories
        """
    )
    conn.execute("DROP TABLE categories")
    conn.execute("ALTER TABLE categories__new RENAME TO categories")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_categories_tenant_id ON categories(tenant_id)")
    conn.execute("PRAGMA foreign_keys=ON")


def migrate() -> None:
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}")
        return
    conn = sqlite3.connect(str(DB_PATH))
    try:
        migrate_categories_table(conn)
        add_column_if_missing(
            conn,
            "products",
            "ALTER TABLE products ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)",
        )
        add_column_if_missing(
            conn,
            "customers",
            "ALTER TABLE customers ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)",
        )
        add_column_if_missing(
            conn,
            "sales",
            "ALTER TABLE sales ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)",
        )
        add_column_if_missing(
            conn,
            "store_settings",
            "ALTER TABLE store_settings ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)",
        )
        add_column_if_missing(
            conn,
            "layby_customers",
            "ALTER TABLE layby_customers ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)",
        )
        add_column_if_missing(
            conn,
            "withdrawals",
            "ALTER TABLE withdrawals ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)",
        )
        add_column_if_missing(
            conn,
            "cashier_shifts",
            "ALTER TABLE cashier_shifts ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)",
        )
        add_column_if_missing(
            conn,
            "notifications",
            "ALTER TABLE notifications ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)",
        )
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_products_tenant_id ON products(tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_customers_tenant_id ON customers(tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_sales_tenant_id ON sales(tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_store_settings_tenant_id ON store_settings(tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_layby_customers_tenant_id ON layby_customers(tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_withdrawals_tenant_id ON withdrawals(tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_cashier_shifts_tenant_id ON cashier_shifts(tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_notifications_tenant_id ON notifications(tenant_id)",
        ):
            conn.execute(stmt)
        conn.commit()
        print("Tenant isolation migration done.")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
