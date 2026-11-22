"""
branches.manager_user_id ↔ users.branch_id is an intentional circular FK.

SQLAlchemy must sort metadata without SAWarning (use_alter on manager FK).
"""
from __future__ import annotations

import warnings

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.enterprise_models import Branch
from app.models import User
from app.quotation_models import Tenant

import app.accounting_models  # noqa: F401
import app.branch_models  # noqa: F401
import app.enterprise_models  # noqa: F401
import app.models  # noqa: F401
import app.saas_models  # noqa: F401


def _cycle_warnings(recorded) -> list:
    return [
        w
        for w in recorded
        if issubclass(w.category, SAWarning)
        and "unresolvable cycles" in str(w.message)
        and "branches" in str(w.message)
        and "users" in str(w.message)
    ]


def test_metadata_sorted_tables_no_branches_users_cycle_warning():
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always", SAWarning)
        tables = Base.metadata.sorted_tables
        assert any(t.name == "branches" for t in tables)
        assert any(t.name == "users" for t in tables)
    assert _cycle_warnings(recorded) == []


def test_migrate_branches_apply_no_cycle_warning():
    import migrate_branches as mb

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    # Minimal pre-existing app tables (migration creates branch tables).
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables["tenants"],
            Base.metadata.tables["users"],
            Base.metadata.tables["categories"],
            Base.metadata.tables["products"],
            Base.metadata.tables["customers"],
            Base.metadata.tables["sales"],
            Base.metadata.tables["cashier_shifts"],
            Base.metadata.tables["expenses"],
            Base.metadata.tables["cash_movements"],
            Base.metadata.tables["refunds"],
            Base.metadata.tables["withdrawals"],
            Base.metadata.tables["inventory_movements"],
        ],
    )
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always", SAWarning)
        report = mb.apply_migration(bind=engine)
    assert report.get("committed") is True
    assert _cycle_warnings(recorded) == []


def test_branch_manager_and_user_branch_assignment_still_work():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = Session()
    try:
        t = Tenant(tenant_uid="fk-cycle-tenant", name="FK Cycle Shop")
        db.add(t)
        db.flush()
        br = Branch(
            tenant_id=t.id,
            name="Main Branch",
            code="MAIN",
            is_default=True,
            is_active=True,
        )
        db.add(br)
        db.flush()
        from app import auth as auth_mod

        u = User(
            username="fk_mgr",
            password_hash=auth_mod.get_password_hash("Pass1234"),
            role="admin",
            tenant_id=t.id,
            branch_id=br.id,
            is_active=True,
        )
        db.add(u)
        db.flush()
        br.manager_user_id = u.id
        db.commit()
        db.refresh(br)
        db.refresh(u)
        assert u.branch_id == br.id
        assert br.manager_user_id == u.id

        fks = {tuple(fk["constrained_columns"]): fk["referred_table"] for fk in inspect(engine).get_foreign_keys("branches")}
        assert ("manager_user_id",) in fks
        assert fks[("manager_user_id",)] == "users"
        user_fks = {
            tuple(fk["constrained_columns"]): fk["referred_table"]
            for fk in inspect(engine).get_foreign_keys("users")
        }
        assert ("branch_id",) in user_fks
        assert user_fks[("branch_id",)] == "branches"
    finally:
        db.close()
