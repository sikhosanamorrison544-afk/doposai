"""
Production-safety tests for migrate_branches.py CLI contract.

Verifies the mutually-exclusive --dry-run / --verify / --apply modes, read-only
guarantees, complete schema verification, duplicate-code guard, and PostgreSQL
transaction rollback semantics. Uses in-memory SQLite and mocks (no real
PostgreSQL instance is required).
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-only-jwt-secret-key-do-not-use-in-prod-64b",
)

from app import auth as auth_mod
from app.database import Base
from app.enterprise_models import Branch, BranchProductStock
from app.models import Product, User
from app.quotation_models import Tenant

import app.accounting_models  # noqa: F401
import app.enterprise_models  # noqa: F401
import app.branch_models  # noqa: F401

import migrate_branches as mb


def _engine() -> "create_engine":
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )


@pytest.fixture()
def full_engine():
    e = _engine()
    Base.metadata.create_all(e)
    return e


@pytest.fixture()
def empty_engine():
    return _engine()


def _monkeypatch_globals(monkeypatch, engine):
    monkeypatch.setattr(mb, "engine", engine)
    monkeypatch.setattr(mb, "SessionLocal", sessionmaker(bind=engine, future=True))


class FakePGConnection:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakePGBegin:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        return False  # propagate exceptions


class FakePGEngine:
    dialect = type("Dialect", (), {"name": "postgresql"})()

    def __init__(self):
        self.conn = FakePGConnection()

    def begin(self):
        return FakePGBegin(self.conn)


# ---------------------------------------------------------------------------
# 1. No arguments → non-zero, no mutations
# ---------------------------------------------------------------------------
def test_no_args_no_mutations(monkeypatch):
    create_calls = {"n": 0}
    apply_calls = {"n": 0}

    def _create_all(*a, **k):
        create_calls["n"] += 1

    def _apply(*a, **k):
        apply_calls["n"] += 1

    monkeypatch.setattr(mb.Base.metadata, "create_all", _create_all)
    monkeypatch.setattr(mb, "apply_migration", _apply)

    assert mb.main([]) != 0
    assert create_calls["n"] == 0
    assert apply_calls["n"] == 0


# ---------------------------------------------------------------------------
# 2. --dry-run never calls create_all or apply_migration
# 3. --verify never calls create_all or apply_migration
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["--dry-run", "--verify"])
def test_read_only_modes_never_mutate(mode, full_engine, monkeypatch):
    _monkeypatch_globals(monkeypatch, full_engine)
    create_calls = {"n": 0}
    apply_calls = {"n": 0}

    def _create_all(*a, **k):
        create_calls["n"] += 1

    def _apply(*a, **k):
        apply_calls["n"] += 1

    monkeypatch.setattr(mb.Base.metadata, "create_all", _create_all)
    monkeypatch.setattr(mb, "apply_migration", _apply)

    # Fully migrated empty fixture: schema valid, no backfill gaps.
    rc = mb.main([mode])
    assert rc == 0
    assert create_calls["n"] == 0
    assert apply_calls["n"] == 0


# ---------------------------------------------------------------------------
# 4. --apply is the only mutating mode
# ---------------------------------------------------------------------------
def test_apply_is_the_only_mutating_mode(full_engine, monkeypatch):
    _monkeypatch_globals(monkeypatch, full_engine)
    apply_calls = {"n": 0}
    real_apply = mb.apply_migration

    def _apply(*a, **k):
        apply_calls["n"] += 1
        return real_apply(*a, **k)

    monkeypatch.setattr(mb, "apply_migration", _apply)
    rc = mb.main(["--apply"])
    assert rc == 0
    assert apply_calls["n"] == 1


# ---------------------------------------------------------------------------
# 5. dry-run reports missing schema and exits 2
# ---------------------------------------------------------------------------
def test_dry_run_missing_schema_exit_2(empty_engine, monkeypatch):
    _monkeypatch_globals(monkeypatch, empty_engine)
    assert mb.main(["--dry-run"]) == 2


# ---------------------------------------------------------------------------
# 6. verify reports missing schema and exits 1
# ---------------------------------------------------------------------------
def test_verify_missing_schema_exit_1(empty_engine, monkeypatch):
    _monkeypatch_globals(monkeypatch, empty_engine)
    assert mb.main(["--verify"]) == 1


# ---------------------------------------------------------------------------
# 7. verify checks every required column/table
# ---------------------------------------------------------------------------
def test_verify_checks_every_required_column(full_engine):
    result = mb.verify_branch_schema(full_engine)
    for t in mb.REQUIRED_TABLES:
        assert result[f"table:{t}"] is True
    for t, cols in mb.REQUIRED_COLUMNS.items():
        for c in cols:
            assert result[f"{t}.{c}"] is True


def test_verify_missing_column_reported(empty_engine):
    result = mb.verify_branch_schema(empty_engine)
    # Empty DB: every required table + column must be reported False.
    assert any(v is False for v in result.values())
    assert result["table:branches"] is False
    assert result["branches.email"] is False


# ---------------------------------------------------------------------------
# 8. Duplicate branch codes block unique-index creation
# ---------------------------------------------------------------------------
class FakeConn:
    """Records executed SQL; returns pre-configured result rows."""

    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, statement, params=None):
        self.executed.append(str(statement))
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


def test_duplicate_branch_codes_block_index(monkeypatch):
    # Simulate two non-null (tenant_id, code) duplicates already present.
    conn = FakeConn(rows=[(1, "MAIN", 2)])
    with pytest.raises(RuntimeError) as ei:
        mb.ensure_postgres_extras(conn)
    assert "duplicate" in str(ei.value).lower()
    # Must not attempt the CREATE INDEX when duplicates exist.
    assert not any("CREATE UNIQUE INDEX" in s for s in conn.executed)


# ---------------------------------------------------------------------------
# 9. schema failure rolls back PostgreSQL application logic
# ---------------------------------------------------------------------------
def test_apply_rolls_back_postgres_on_schema_failure(monkeypatch):
    fake = FakePGEngine()

    def _noop_create_all(*a, **k):
        return None

    def _boom(conn):
        raise RuntimeError("ddl failure")

    monkeypatch.setattr(mb.Base.metadata, "create_all", _noop_create_all)
    monkeypatch.setattr(mb, "ensure_schema_columns", _boom)

    with pytest.raises(RuntimeError):
        mb.apply_migration(bind=fake)

    assert fake.conn.rolled_back is True
    assert fake.conn.committed is False


# ---------------------------------------------------------------------------
# 10. apply followed by verify succeeds on an SQLite fixture
# ---------------------------------------------------------------------------
def _seed_tenant_data(engine):
    Session = sessionmaker(bind=engine, future=True)
    db = Session()
    t = Tenant(tenant_uid=str(uuid.uuid4()), name="Apply Co")
    db.add(t)
    db.flush()
    tid = t.id
    db.add(
        User(
            username="apply_admin",
            password_hash=auth_mod.get_password_hash("AdminPass1234"),
            role="admin",
            tenant_id=tid,
            is_active=True,
        )
    )
    db.add(
        Product(
            name="Widget",
            barcode="W-APPLY",
            selling_price=10,
            cost_price=4,
            stock_qty=5,
            reserved_qty=0,
            tenant_id=tid,
        )
    )
    db.commit()
    db.close()
    return tid


def test_apply_then_verify_succeeds(full_engine, monkeypatch):
    _monkeypatch_globals(monkeypatch, full_engine)
    tid = _seed_tenant_data(full_engine)

    assert mb.main(["--apply"]) == 0
    assert mb.main(["--verify"]) == 0

    Session = sessionmaker(bind=full_engine, future=True)
    db = Session()
    branch = db.query(Branch).filter(Branch.tenant_id == tid).one()
    assert branch.is_default is True
    assert db.query(BranchProductStock).filter(
        BranchProductStock.branch_id == branch.id
    ).count() == 1
    db.close()


# ---------------------------------------------------------------------------
# 11. rerunning --apply is idempotent
# ---------------------------------------------------------------------------
def test_apply_is_idempotent(full_engine, monkeypatch):
    _monkeypatch_globals(monkeypatch, full_engine)
    tid = _seed_tenant_data(full_engine)

    assert mb.main(["--apply"]) == 0
    assert mb.main(["--apply"]) == 0

    Session = sessionmaker(bind=full_engine, future=True)
    db = Session()
    assert db.query(Branch).filter(Branch.tenant_id == tid).count() == 1
    assert db.query(BranchProductStock).count() == 1
    assert db.query(Product).count() == 1
    db.close()


# ---------------------------------------------------------------------------
# 12. existing migration/backfill tests remain green (guarded by the suite)
# ---------------------------------------------------------------------------
def test_helpers_preserve_signatures_for_existing_tests(full_engine):
    Session = sessionmaker(bind=full_engine, future=True)
    db = Session()
    t = Tenant(tenant_uid=str(uuid.uuid4()), name="Helpers Co")
    db.add(t)
    db.flush()
    main = mb.ensure_main_branch(db, t.id)
    assert main.is_default is True
    assert mb.ensure_user_memberships(db, t.id, main) >= 0
    assert mb.ensure_branch_inventory(db, t.id, main) == 0
    assert isinstance(mb.backfill_transaction_branch_ids(db, t.id, main), dict)
    db.close()