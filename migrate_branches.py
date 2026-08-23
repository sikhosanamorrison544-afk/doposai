#!/usr/bin/env python3
"""
Multi-branch foundation migration (additive, idempotent, production-safe).

Creates / ensures:
  - branches table columns (email, manager_user_id, unique code)
  - user_branches membership table
  - branch_product_stock tenant_id / reorder fields / seeded_from_legacy
  - stock_transfers actor + idempotency columns
  - stock_transfer_items dispatch/damage columns
  - refunds.branch_id, withdrawals.branch_id
  - inventory_movements.tenant_id / branch_id / client_movement_id +
    movement_type / reference_type / reference_id provenance
  - one Main Branch (code=MAIN, is_default) per tenant
  - UserBranch for existing users
  - BranchProductStock rows from Product.stock_qty
  - backfill branch_id on sales, shifts, refunds, expenses, withdrawals,
    cash_movements, users (legacy assignment)

Does NOT alter historical amounts, costs, dates, or journal entries.
Does NOT run against production unless explicitly invoked with DATABASE_URL.

Usage (exactly one mode required):
  python3 migrate_branches.py --dry-run   # inspection only, exit 0/2
  python3 migrate_branches.py --verify    # inspection only, exit 0/1
  python3 migrate_branches.py --apply     # mutate + verify, exit 0/1
"""
from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from sqlalchemy import func, inspect, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app import models  # noqa: F401, E402
from app import enterprise_models  # noqa: F401, E402
from app import branch_models  # noqa: F401, E402
from app import accounting_models  # noqa: F401, E402
from app.quotation_models import Tenant  # noqa: F401, E402
from app.enterprise_models import Branch, BranchProductStock  # noqa: E402
from app.branch_models import UserBranch  # noqa: E402
from app.models import (  # noqa: E402
    CashMovement,
    CashierShift,
    Expense,
    InventoryMovement,
    Product,
    Refund,
    Sale,
    User,
    Withdrawal,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_branches")

MAIN_BRANCH_NAME = "Main Branch"
MAIN_BRANCH_CODE = "MAIN"

# --- Internal constants only. Never accept table/column names from input. ---

REQUIRED_TABLES = (
    "branches",
    "user_branches",
    "branch_product_stock",
    "stock_transfers",
    "stock_transfer_items",
)

REQUIRED_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "branches": ("email", "manager_user_id"),
    "user_branches": ("updated_at",),
    "branch_product_stock": (
        "tenant_id",
        "reorder_level",
        "reorder_quantity",
        "seeded_from_legacy",
    ),
    "stock_transfers": (
        "requested_by_id",
        "approved_by_id",
        "dispatched_by_id",
        "requested_at",
        "approved_at",
        "client_transfer_id",
    ),
    "stock_transfer_items": (
        "quantity_dispatched",
        "quantity_damaged",
        "notes",
    ),
    "refunds": ("branch_id",),
    "withdrawals": ("branch_id",),
    "inventory_movements": (
        "tenant_id",
        "branch_id",
        "client_movement_id",
        "movement_type",
        "reference_type",
        "reference_id",
    ),
    "journal_entries": ("branch_id",),
}

COLUMN_DDL: List[Tuple[str, str, str]] = [
    ("branches", "email", "VARCHAR(120)"),
    ("branches", "manager_user_id", "INTEGER"),
    ("branch_product_stock", "tenant_id", "INTEGER"),
    ("branch_product_stock", "reorder_level", "FLOAT"),
    ("branch_product_stock", "reorder_quantity", "FLOAT"),
    ("stock_transfers", "requested_by_id", "INTEGER"),
    ("stock_transfers", "approved_by_id", "INTEGER"),
    ("stock_transfers", "dispatched_by_id", "INTEGER"),
    ("stock_transfers", "requested_at", "TIMESTAMP"),
    ("stock_transfers", "approved_at", "TIMESTAMP"),
    ("stock_transfers", "client_transfer_id", "VARCHAR(64)"),
    ("stock_transfer_items", "quantity_dispatched", "FLOAT"),
    ("stock_transfer_items", "quantity_damaged", "FLOAT"),
    ("stock_transfer_items", "notes", "TEXT"),
    ("refunds", "branch_id", "INTEGER"),
    ("withdrawals", "branch_id", "INTEGER"),
    ("inventory_movements", "tenant_id", "INTEGER"),
    ("inventory_movements", "branch_id", "INTEGER"),
    ("inventory_movements", "client_movement_id", "VARCHAR(64)"),
    ("inventory_movements", "movement_type", "VARCHAR(40)"),
    ("inventory_movements", "reference_type", "VARCHAR(40)"),
    ("inventory_movements", "reference_id", "INTEGER"),
    ("user_branches", "updated_at", "TIMESTAMP"),
    ("branch_product_stock", "seeded_from_legacy", "BOOLEAN DEFAULT FALSE"),
    ("journal_entries", "branch_id", "INTEGER"),
]

UNIQUE_INDEX_NAME = "uq_branches_tenant_code"


# --- Read-only inspection helpers -----------------------------------------


def _dialect(bind: Any) -> str:
    """Return the dialect name (sqlite / postgresql) for an engine or connection."""
    if hasattr(bind, "dialect"):
        return (bind.dialect.name or "").lower()
    engine_ = getattr(bind, "engine", None)
    if engine_ is not None and hasattr(engine_, "dialect"):
        return (engine_.dialect.name or "").lower()
    return ""


def _table_names(bind: Any) -> Set[str]:
    return set(inspect(bind).get_table_names())


def _table_columns(bind: Any, table: str) -> Set[str]:
    insp = inspect(bind)
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _index_names(bind: Any, table: str) -> Set[str]:
    insp = inspect(bind)
    try:
        return {ix["name"] for ix in insp.get_indexes(table)}
    except Exception:
        return set()


def missing_required_schema(bind: Any) -> List[str]:
    """Read-only list of missing tables/columns; never creates anything."""
    tables = _table_names(bind)
    gaps: List[str] = []
    for t in REQUIRED_TABLES:
        if t not in tables:
            gaps.append(f"table:{t}")
    for t, cols in REQUIRED_COLUMNS.items():
        existing = _table_columns(bind, t)
        for c in cols:
            if c not in existing:
                gaps.append(f"{t}.{c}")
    return gaps


def verify_branch_schema(bind: Any = None) -> Dict[str, bool]:
    """Complete post-migration schema verification (read-only)."""
    binding = bind if bind is not None else engine
    tables = _table_names(binding)
    out: Dict[str, bool] = {f"table:{t}": t in tables for t in REQUIRED_TABLES}
    for t, cols in REQUIRED_COLUMNS.items():
        existing = _table_columns(binding, t)
        for c in cols:
            out[f"{t}.{c}"] = c in existing
    # Partial unique index only meaningful on PostgreSQL.
    if _dialect(binding) == "postgresql":
        out[f"index:{UNIQUE_INDEX_NAME}"] = UNIQUE_INDEX_NAME in _index_names(binding, "branches")
    else:
        out[f"index:{UNIQUE_INDEX_NAME}"] = True
    return out


# --- Additive DDL (apply only) ---------------------------------------------


def add_column_if_missing(conn, table: str, column: str, ddl: str) -> bool:
    """Add a column on the SAME connection/transaction; no error suppression."""
    cols = _table_columns(conn, table)
    if column in cols:
        return False
    dialect = _dialect(conn)
    if dialect == "postgresql":
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}"))
    else:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    logger.info("Added %s.%s", table, column)
    return True


def ensure_schema_columns(conn) -> List[str]:
    """Add all missing additive columns using the provided transaction connection."""
    added: List[str] = []
    for table, col, ddl in COLUMN_DDL:
        if not inspect(conn).has_table(table):
            continue
        if add_column_if_missing(conn, table, col, ddl):
            added.append(f"{table}.{col}")
    return added


def _duplicate_branch_codes(conn) -> List[Tuple[Optional[int], str, int]]:
    """Detect duplicate non-null (tenant_id, code) pairs before unique-index creation."""
    rows = conn.execute(
        text(
            "SELECT tenant_id, code, COUNT(*) FROM branches "
            "WHERE code IS NOT NULL AND tenant_id IS NOT NULL "
            "GROUP BY tenant_id, code HAVING COUNT(*) > 1"
        )
    ).fetchall()
    return [tuple(r) for r in rows]


def _postgres_column_type(conn, table: str, column: str) -> Optional[str]:
    row = conn.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).first()
    return row[0] if row else None


def ensure_postgres_extras(conn) -> List[str]:
    """PostgreSQL-only index + numeric promotion. Aborts (raises) on any failure.
    Never suppresses DDL errors or silently continues past duplicates/conversion."""
    added: List[str] = []

    dups = _duplicate_branch_codes(conn)
    if dups:
        raise RuntimeError(
            "Duplicate non-null (tenant_id, code) branches block unique-index creation: "
            f"{dups!r}"
        )
    conn.execute(
        text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {UNIQUE_INDEX_NAME} "
            "ON branches (tenant_id, code) WHERE code IS NOT NULL"
        )
    )
    added.append(f"index:{UNIQUE_INDEX_NAME}")

    # Promote BPS quantities to NUMERIC(18,4) only when actually required.
    for col in ("stock_qty", "reserved_qty"):
        col_type = _postgres_column_type(conn, "branch_product_stock", col)
        if col_type is None or col_type.lower() in ("numeric", "decimal"):
            continue  # already numeric, or column absent (handled by additive step)
        conn.execute(
            text(
                f"ALTER TABLE branch_product_stock "
                f"ALTER COLUMN {col} TYPE NUMERIC(18,4) USING {col}::numeric"
            )
        )
        added.append(f"bps:{col}:numeric")
    return added


# --- Data backfill (apply only, bound to migrated transaction) -------------


def _tenant_ids(db: Session) -> List[Optional[int]]:
    ids = [t.id for t in db.query(Tenant).order_by(Tenant.id).all()]
    # Include legacy NULL-tenant space if products/users exist with NULL tid
    has_null = (
        db.query(User.id).filter(User.tenant_id.is_(None)).first() is not None
        or db.query(Product.id).filter(Product.tenant_id.is_(None)).first() is not None
        or db.query(Sale.id).filter(Sale.tenant_id.is_(None)).first() is not None
    )
    out: List[Optional[int]] = list(ids)
    if has_null and None not in out:
        out.append(None)
    return out


def ensure_main_branch(db: Session, tenant_id: Optional[int]) -> Branch:
    q = db.query(Branch)
    if tenant_id is None:
        q = q.filter(Branch.tenant_id.is_(None))
    else:
        q = q.filter(Branch.tenant_id == tenant_id)
    existing = (
        q.filter(Branch.is_default.is_(True)).order_by(Branch.id.asc()).first()
        or q.filter(Branch.code == MAIN_BRANCH_CODE).order_by(Branch.id.asc()).first()
        or q.filter(Branch.name == MAIN_BRANCH_NAME).order_by(Branch.id.asc()).first()
    )
    if existing is not None:
        changed = False
        if not existing.is_default:
            existing.is_default = True
            changed = True
        if not (existing.code or "").strip():
            existing.code = MAIN_BRANCH_CODE
            changed = True
        if not (existing.name or "").strip():
            existing.name = MAIN_BRANCH_NAME
            changed = True
        if changed:
            db.flush()
        return existing
    br = Branch(
        tenant_id=tenant_id,
        name=MAIN_BRANCH_NAME,
        code=MAIN_BRANCH_CODE,
        is_default=True,
        is_active=True,
    )
    db.add(br)
    db.flush()
    logger.info("Created Main Branch for tenant_id=%s id=%s", tenant_id, br.id)
    return br


def ensure_user_memberships(db: Session, tenant_id: Optional[int], main: Branch) -> int:
    created = 0
    uq = db.query(User)
    if tenant_id is None:
        uq = uq.filter(User.tenant_id.is_(None))
    else:
        uq = uq.filter(User.tenant_id == tenant_id)
    for user in uq.all():
        target_branch_id = int(user.branch_id) if user.branch_id else int(main.id)
        br = db.query(Branch).filter(Branch.id == target_branch_id).first()
        if br is None or (
            (tenant_id is None and br.tenant_id is not None)
            or (tenant_id is not None and br.tenant_id != tenant_id)
        ):
            target_branch_id = int(main.id)
        existing = (
            db.query(UserBranch)
            .filter(UserBranch.user_id == user.id, UserBranch.branch_id == target_branch_id)
            .first()
        )
        if existing is None:
            role = (user.role or "cashier").strip().lower()
            if role in ("admin", "owner"):
                mrole = "owner"
            elif role == "supervisor":
                mrole = "manager"
            else:
                mrole = "cashier"
            db.add(
                UserBranch(
                    tenant_id=tenant_id,
                    user_id=user.id,
                    branch_id=target_branch_id,
                    role=mrole,
                    is_default=True,
                    is_active=True,
                )
            )
            created += 1
        if user.branch_id is None:
            user.branch_id = target_branch_id
    db.flush()
    return created


def ensure_branch_inventory(db: Session, tenant_id: Optional[int], main: Branch) -> int:
    """Idempotent Main Branch seed. Never re-copies Product.stock_qty once a row exists."""
    created = 0
    pq = db.query(Product)
    if tenant_id is None:
        pq = pq.filter(Product.tenant_id.is_(None))
    else:
        pq = pq.filter(Product.tenant_id == tenant_id)
    for product in pq.all():
        row = (
            db.query(BranchProductStock)
            .filter(
                BranchProductStock.branch_id == main.id,
                BranchProductStock.product_id == product.id,
            )
            .first()
        )
        if row is None:
            db.add(
                BranchProductStock(
                    tenant_id=tenant_id,
                    branch_id=main.id,
                    product_id=product.id,
                    stock_qty=Decimal(str(product.stock_qty or 0)),
                    reserved_qty=Decimal(str(getattr(product, "reserved_qty", 0) or 0)),
                    seeded_from_legacy=True,
                )
            )
            created += 1
        else:
            if row.tenant_id is None and tenant_id is not None:
                row.tenant_id = tenant_id
            if getattr(row, "seeded_from_legacy", None) is False:
                row.seeded_from_legacy = True
    db.flush()
    return created


def backfill_transaction_branch_ids(
    db: Session, tenant_id: Optional[int], main: Branch
) -> Dict[str, int]:
    """Set NULL branch_id on transactional rows to Main Branch (idempotent)."""
    counts = {
        "sales": 0,
        "shifts": 0,
        "refunds": 0,
        "expenses": 0,
        "withdrawals": 0,
        "cash_movements": 0,
    }

    def _tid_filter(model, q):
        if tenant_id is None:
            return q.filter(model.tenant_id.is_(None))
        return q.filter(model.tenant_id == tenant_id)

    for sale in _tid_filter(Sale, db.query(Sale).filter(Sale.branch_id.is_(None))).all():
        sale.branch_id = main.id
        counts["sales"] += 1
    for sh in _tid_filter(CashierShift, db.query(CashierShift).filter(CashierShift.branch_id.is_(None))).all():
        sh.branch_id = main.id
        counts["shifts"] += 1
    for rf in _tid_filter(Refund, db.query(Refund).filter(Refund.branch_id.is_(None))).all():
        if rf.sale_id:
            sale = db.query(Sale).filter(Sale.id == rf.sale_id).first()
            rf.branch_id = int(sale.branch_id) if sale and sale.branch_id else main.id
        else:
            rf.branch_id = main.id
        counts["refunds"] += 1
    for ex in _tid_filter(Expense, db.query(Expense).filter(Expense.branch_id.is_(None))).all():
        ex.branch_id = main.id
        counts["expenses"] += 1
    for wd in _tid_filter(Withdrawal, db.query(Withdrawal).filter(Withdrawal.branch_id.is_(None))).all():
        wd.branch_id = main.id
        counts["withdrawals"] += 1
    for cm in _tid_filter(CashMovement, db.query(CashMovement).filter(CashMovement.branch_id.is_(None))).all():
        cm.branch_id = main.id
        counts["cash_movements"] += 1
    db.flush()
    return counts


# --- Read-only backfill verification ---------------------------------------


def verify_backfill(db: Session, bind: Any = None) -> Dict[str, Any]:
    """Verify data invariants. Read-only: returns schema_gaps without ORM SELECTs
    when required tables/columns are absent (no create_all is performed)."""
    binding = bind if bind is not None else engine
    report: Dict[str, Any] = {"tenants": [], "ok": True, "global": {}}

    # Guard: never run ORM SELECTs that reference missing columns.
    schema_gaps = missing_required_schema(binding)
    if schema_gaps:
        report["ok"] = False
        report["schema_gaps"] = schema_gaps
        return report

    # Cross-tenant memberships + branch/membership tenant alignment.
    bad_mem = 0
    for m in db.query(UserBranch).all():
        u = db.query(User).filter(User.id == m.user_id).first()
        br = db.query(Branch).filter(Branch.id == m.branch_id).first()
        if not u or not br:
            bad_mem += 1
            continue
        if u.tenant_id != br.tenant_id or (
            m.tenant_id is not None and m.tenant_id != u.tenant_id
        ):
            bad_mem += 1
    report["global"]["cross_tenant_memberships"] = bad_mem
    if bad_mem:
        report["ok"] = False

    # Branches referencing a non-existent tenant (never crosses tenants).
    orphan_branches = 0
    for b in db.query(Branch).filter(Branch.tenant_id.isnot(None)).all():
        if db.query(Tenant).filter(Tenant.id == b.tenant_id).first() is None:
            orphan_branches += 1
    report["global"]["orphan_branches"] = orphan_branches
    if orphan_branches:
        report["ok"] = False

    # No user may have multiple active default memberships.
    dup_defaults = (
        db.query(UserBranch.user_id, func.count(UserBranch.id))
        .filter(UserBranch.is_active.is_(True), UserBranch.is_default.is_(True))
        .group_by(UserBranch.user_id)
        .having(func.count(UserBranch.id) > 1)
        .count()
    )
    report["global"]["users_with_multiple_defaults"] = dup_defaults
    if dup_defaults:
        report["ok"] = False

    # Every product must have a BranchProductStock row and a consistent shadow.
    products_missing_bps = 0
    stock_shadow_mismatch = 0
    for p in db.query(Product).all():
        has_row = (
            db.query(BranchProductStock.id)
            .filter(BranchProductStock.product_id == p.id)
            .first()
            is not None
        )
        if not has_row:
            products_missing_bps += 1
        total = (
            db.query(func.coalesce(func.sum(BranchProductStock.stock_qty), 0))
            .filter(BranchProductStock.product_id == p.id)
            .scalar()
        )
        if abs(float(total or 0) - float(p.stock_qty or 0)) > 1e-9:
            stock_shadow_mismatch += 1
    report["global"]["products_missing_branch_stock"] = products_missing_bps
    report["global"]["product_stock_shadow_mismatch"] = stock_shadow_mismatch
    if products_missing_bps or stock_shadow_mismatch:
        report["ok"] = False

    for tid in _tenant_ids(db):
        q = db.query(Branch)
        if tid is None:
            q = q.filter(Branch.tenant_id.is_(None))
        else:
            q = q.filter(Branch.tenant_id == tid)
        mains = q.filter(Branch.is_default.is_(True)).all()
        entry = {
            "tenant_id": tid,
            "main_branch_count": len(mains),
            "branch_count": q.count(),
        }
        if len(mains) != 1:
            entry["error"] = "expected exactly one Main Branch (is_default)"
            report["ok"] = False
        codes = [
            b.code
            for b in q.filter(Branch.code.isnot(None)).all()
            if (b.code or "").strip()
        ]
        if len(codes) != len(set(codes)):
            entry["duplicate_codes"] = True
            report["ok"] = False
        sq = db.query(Sale)
        if tid is None:
            sq = sq.filter(Sale.tenant_id.is_(None))
        else:
            sq = sq.filter(Sale.tenant_id == tid)
        entry["sales_null_branch"] = sq.filter(Sale.branch_id.is_(None)).count()
        if entry["sales_null_branch"]:
            report["ok"] = False
        report["tenants"].append(entry)
    return report


# --- Apply (the only mutating path) ----------------------------------------


def apply_migration(bind: Any = None) -> Dict[str, Any]:
    """Apply the migration as one coordinated transaction, then leave the DB
    committed. For PostgreSQL all schema creation, additive DDL, and data
    backfill share a single ``engine.begin()`` transaction bound to one ORM
    session; any exception rolls the whole transaction back. SQLite is
    idempotent (note limitation)."""
    binding = bind if bind is not None else engine
    dialect = _dialect(binding)
    report: Dict[str, Any] = {"dialect": dialect, "added_columns": [], "tenants": []}
    if dialect == "sqlite":
        report["limitations"] = [
            "SQLite does not support fully transactional DDL; the migration is "
            "idempotent — rerun --apply if interrupted part-way."
        ]

    with binding.begin() as conn:
        # New tables on the SAME transaction connection.
        Base.metadata.create_all(bind=conn)
        report["added_columns"] = ensure_schema_columns(conn)
        if dialect == "postgresql":
            report["postgres_extras"] = ensure_postgres_extras(conn)

        # ORM session bound to the same connection (no session.commit inside).
        db = Session(bind=conn)
        try:
            for tid in _tenant_ids(db):
                main = ensure_main_branch(db, tid)
                mem = ensure_user_memberships(db, tid, main)
                inv = ensure_branch_inventory(db, tid, main)
                backfill = backfill_transaction_branch_ids(db, tid, main)
                report["tenants"].append(
                    {
                        "tenant_id": tid,
                        "main_branch_id": main.id,
                        "memberships_created": mem,
                        "inventory_rows_created": inv,
                        "backfill": backfill,
                    }
                )
            db.flush()  # flush through the bound session; commit via engine.begin()
        finally:
            db.close()
    report["committed"] = True
    return report


# --- Verification report shared by --verify / (post-)--apply ---------------


def _verification_report(bind: Any) -> Dict[str, Any]:
    checklist = verify_branch_schema(bind)
    db = SessionLocal()
    try:
        bf = verify_backfill(db, bind)
    finally:
        db.close()
    return {"schema": checklist, "backfill": bf}


def _report_clean(report: Dict[str, Any]) -> bool:
    schema_ok = all(report["schema"].values())
    backfill_ok = bool(report["backfill"].get("ok", True))
    return schema_ok and backfill_ok


def _log_verification(prefix: str, report: Dict[str, Any]) -> None:
    for k in sorted(report["schema"]):
        logger.info("%s schema %s = %s", prefix, k, report["schema"][k])
    logger.info("%s backfill: %s", prefix, report["backfill"])


# --- CLI -------------------------------------------------------------------


def _run_dry_run() -> int:
    report = _verification_report(engine)
    _log_verification("DRY-RUN", report)
    if not _report_clean(report):
        missing = [k for k, v in report["schema"].items() if not v]
        logger.warning(
            "Dry-run found gaps: schema=%s backfill_ok=%s",
            missing,
            report["backfill"].get("ok"),
        )
        return 2
    logger.info("DRY-RUN: schema and backfill invariants look ready (no work needed)")
    return 0


def _run_verify() -> int:
    report = _verification_report(engine)
    _log_verification("VERIFY", report)
    if not _report_clean(report):
        missing = [k for k, v in report["schema"].items() if not v]
        logger.error(
            "Branch migration verification failed: schema=%s backfill_ok=%s",
            missing,
            report["backfill"].get("ok"),
        )
        return 1
    logger.info("VERIFY: post-migration schema and backfill invariants are valid")
    return 0


def _run_apply() -> int:
    try:
        applied = apply_migration()
    except Exception as e:
        logger.error("Branch migration application failed: %s", e)
        return 1
    logger.info("Migration report: %s", applied)

    report = _verification_report(engine)
    _log_verification("VERIFY", report)
    if not _report_clean(report):
        missing = [k for k, v in report["schema"].items() if not v]
        logger.error(
            "Post-apply verification failed: schema=%s backfill_ok=%s",
            missing,
            report["backfill"].get("ok"),
        )
        return 1
    logger.info("Branch foundation migration complete.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="Inspection only; exit 0/2.")
    group.add_argument("--verify", action="store_true", help="Inspection only; exit 0/1.")
    group.add_argument("--apply", action="store_true", help="Apply then verify; exit 0/1.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    modes = [name for name in ("dry_run", "verify", "apply") if getattr(args, name)]
    if len(modes) != 1:
        parser.print_help(sys.stderr)
        return 2

    if args.dry_run:
        return _run_dry_run()
    if args.verify:
        return _run_verify()
    if args.apply:
        return _run_apply()
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())