"""
Idempotent financial-accuracy schema helpers.

Used by:
  - ``migrate_financial_accuracy.py`` (preferred explicit pre-deploy path)
  - ``app.main`` deferred bootstrap (best-effort safety net only)

Prefer running the migration script before deploying application code.
Do not rely solely on startup ``create_all`` for production schema changes.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional, Set

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

# CoA rows required for withdrawal-purpose posting when accounting is initialized.
REQUIRED_COA = (
    ("1050", "Cash Transfers / In Transit", "ASSET", "Till transfers between locations"),
    (
        "1450",
        "Cash Disbursement Clearing",
        "ASSET",
        "Cash out for expense payments / adjustments (not P&L)",
    ),
    ("3300", "Owner Drawings", "EQUITY", "Owner draws from till only"),
)


def table_names(engine: Engine) -> Set[str]:
    return set(inspect(engine).get_table_names())


def columns(engine: Engine, table: str) -> Set[str]:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _dialect_name(conn: Connection) -> str:
    return (conn.dialect.name or "").lower()


def add_column_if_missing(
    conn: Connection,
    table: str,
    column: str,
    ddl_type: str,
    *,
    existing: Optional[Set[str]] = None,
) -> bool:
    """
    Add ``table.column`` when missing. Returns True if the column was added.

    ``ddl_type`` is the SQL type clause only, e.g. ``NUMERIC(10, 2)`` or
    ``VARCHAR(3) DEFAULT 'USD'``.
    """
    cols = existing if existing is not None else None
    if cols is None:
        # Re-inspect via connection engine
        eng = conn.engine
        cols = columns(eng, table)
    if column in cols:
        return False
    # IF NOT EXISTS is PG 9.1+ / modern SQLite; keep simple ADD after inspect.
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
    logger.info("Added %s.%s", table, column)
    return True


def backfill_sale_item_unit_cost(conn: Connection) -> int:
    result = conn.execute(
        text(
            """
            UPDATE sale_items
            SET unit_cost = (
                SELECT products.cost_price FROM products
                WHERE products.id = sale_items.product_id
            )
            WHERE unit_cost IS NULL
            """
        )
    )
    return int(result.rowcount or 0)


def backfill_store_currency(conn: Connection) -> None:
    conn.execute(
        text(
            "UPDATE store_settings SET currency = 'USD' "
            "WHERE currency IS NULL OR TRIM(currency) = ''"
        )
    )


def backfill_withdrawal_purposes(conn: Connection) -> None:
    """Map legacy reason strings to purpose codes. Never invent owner_draw for unknowns."""
    mappings: Iterable[tuple[str, tuple[str, ...]]] = [
        ("owner_draw", ("Owner draw", "Owner Draw", "owner_draw")),
        ("bank_deposit", ("Bank deposit", "Bank Deposit", "bank_deposit")),
        ("cash_transfer", ("Cash transfer", "Cash Transfer", "cash_transfer")),
        (
            "expense_payment",
            (
                "Expense payment",
                "Daily expenses",
                "Salary",
                "Rent",
                "Utilities",
            ),
        ),
        ("cash_adjustment", ("Cash adjustment", "Cash Adjustment")),
        ("other", ("Buying company assets", "Other")),
    ]
    for purpose, reasons in mappings:
        for reason in reasons:
            conn.execute(
                text(
                    "UPDATE withdrawals SET purpose = :purpose "
                    "WHERE (purpose IS NULL OR TRIM(purpose) = '') "
                    "AND lower(reason) = lower(:reason)"
                ),
                {"purpose": purpose, "reason": reason},
            )
    conn.execute(
        text(
            "UPDATE withdrawals SET purpose = 'unclassified' "
            "WHERE purpose IS NULL OR TRIM(purpose) = ''"
        )
    )
    logger.info("Backfilled withdrawals.purpose from reasons")


def ensure_coa_accounts(conn: Connection) -> None:
    """Ensure purpose-related CoA rows exist when accounting is initialized."""
    any_coa = conn.execute(text("SELECT 1 FROM chart_of_accounts LIMIT 1")).fetchone()
    if not any_coa:
        return
    dialect = _dialect_name(conn)
    for code, name, atype, desc in REQUIRED_COA:
        row = conn.execute(
            text("SELECT 1 FROM chart_of_accounts WHERE code = :c LIMIT 1"),
            {"c": code},
        ).fetchone()
        if row is not None:
            continue
        # Include created_at — some deployments have NOT NULL without a DB default.
        if dialect == "postgresql":
            conn.execute(
                text(
                    """
                    INSERT INTO chart_of_accounts
                    (code, name, account_type, parent_id, is_active, description, created_at)
                    VALUES (:code, :name, :atype, NULL, TRUE, :desc, NOW())
                    """
                ),
                {"code": code, "name": name, "atype": atype, "desc": desc},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO chart_of_accounts
                    (code, name, account_type, parent_id, is_active, description, created_at)
                    VALUES (:code, :name, :atype, NULL, 1, :desc, CURRENT_TIMESTAMP)
                    """
                ),
                {"code": code, "name": name, "atype": atype, "desc": desc},
            )
        logger.info("Inserted CoA %s %s", code, name)


def normalize_expense_pending_status(conn: Connection) -> None:
    conn.execute(
        text(
            "UPDATE expenses SET status = 'draft' "
            "WHERE lower(status) = 'pending'"
        )
    )


def ensure_financial_accuracy_schema(engine: Engine, *, create_missing_tables: bool = False) -> dict[str, Any]:
    """
    Idempotent schema ensure + safe backfills.

    Returns a verification dict of present columns/tables.
    """
    report: dict[str, Any] = {"added": [], "tables": {}, "backfilled_unit_cost_rows": 0}
    if create_missing_tables:
        from app.database import Base
        import app.models  # noqa: F401
        import app.accounting_models  # noqa: F401
        import app.enterprise_models  # noqa: F401
        import app.quotation_models  # noqa: F401

        Base.metadata.create_all(bind=engine)

    tables = table_names(engine)
    with engine.begin() as conn:
        if "sale_items" in tables:
            before = columns(engine, "sale_items")
            if add_column_if_missing(
                conn, "sale_items", "unit_cost", "NUMERIC(10, 2)", existing=before
            ):
                report["added"].append("sale_items.unit_cost")
        if "store_settings" in tables:
            before = columns(engine, "store_settings")
            if add_column_if_missing(
                conn,
                "store_settings",
                "currency",
                "VARCHAR(3) DEFAULT 'USD'",
                existing=before,
            ):
                report["added"].append("store_settings.currency")
        if "withdrawals" in tables:
            before = columns(engine, "withdrawals")
            if add_column_if_missing(
                conn, "withdrawals", "purpose", "VARCHAR(40)", existing=before
            ):
                report["added"].append("withdrawals.purpose")

        if "sale_items" in tables and "products" in tables:
            report["backfilled_unit_cost_rows"] = backfill_sale_item_unit_cost(conn)
        if "store_settings" in tables:
            backfill_store_currency(conn)
        if "withdrawals" in tables:
            # purpose column may have just been added in this transaction
            backfill_withdrawal_purposes(conn)
        if "chart_of_accounts" in tables:
            ensure_coa_accounts(conn)
        if "expenses" in tables:
            normalize_expense_pending_status(conn)

    # Post-verify against fresh inspect
    report["tables"] = {
        "sale_items.unit_cost": "unit_cost" in columns(engine, "sale_items"),
        "store_settings.currency": "currency" in columns(engine, "store_settings"),
        "withdrawals.purpose": "purpose" in columns(engine, "withdrawals"),
        "expenses": "expenses" in table_names(engine),
        "cash_movements": "cash_movements" in table_names(engine),
        "refunds": "refunds" in table_names(engine),
        "refund_items": "refund_items" in table_names(engine),
        "journal_entries": "journal_entries" in table_names(engine),
    }
    return report


def verify_financial_schema(engine: Engine) -> dict[str, bool]:
    """Read-only checklist for deploy smoke verification."""
    tables = table_names(engine)
    je_cols = columns(engine, "journal_entries") if "journal_entries" in tables else set()
    refund_cols = columns(engine, "refunds") if "refunds" in tables else set()
    return {
        "sale_items.unit_cost": "unit_cost" in columns(engine, "sale_items"),
        "store_settings.currency": "currency" in columns(engine, "store_settings"),
        "withdrawals.purpose": "purpose" in columns(engine, "withdrawals"),
        "expenses_table": "expenses" in tables,
        "cash_movements_table": "cash_movements" in tables,
        "refunds_table": "refunds" in tables,
        "refund_items_table": "refund_items" in tables,
        "refunds.approved_at": "approved_at" in refund_cols,
        "refunds.tenant_id": "tenant_id" in refund_cols,
        "journal_entries.reference_type": "reference_type" in je_cols,
        "journal_entries.reference_id": "reference_id" in je_cols,
    }
