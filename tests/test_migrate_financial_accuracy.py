"""Idempotent financial schema migration tests (SQLite in-memory)."""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-only-jwt-secret-key-do-not-use-in-prod-64b",
)

from app.database import Base
from app.financial_schema import (
    ensure_financial_accuracy_schema,
    verify_financial_schema,
)
from app.models import Product, Sale, SaleItem, StoreSettings, User, Withdrawal
from app import auth as auth_mod


@pytest.fixture()
def eng():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    import app.accounting_models  # noqa: F401
    import app.enterprise_models  # noqa: F401
    import app.quotation_models  # noqa: F401

    Base.metadata.create_all(engine)
    return engine


def test_migration_idempotent_and_verifies(eng):
    r1 = ensure_financial_accuracy_schema(eng, create_missing_tables=False)
    assert r1["tables"]["sale_items.unit_cost"] is True
    assert r1["tables"]["store_settings.currency"] is True
    assert r1["tables"]["withdrawals.purpose"] is True
    assert r1["tables"]["expenses"] is True
    assert r1["tables"]["cash_movements"] is True

    r2 = ensure_financial_accuracy_schema(eng, create_missing_tables=False)
    assert r2["added"] == []

    checklist = verify_financial_schema(eng)
    assert all(checklist.values()), checklist


def test_unit_cost_and_purpose_backfill(eng):
    Session = sessionmaker(bind=eng, future=True)
    db = Session()
    u = User(
        username="m_admin",
        email="m@ex.com",
        password_hash=auth_mod.get_password_hash("AdminPass1234"),
        role="admin",
        is_active=True,
        full_name="A",
    )
    db.add(u)
    db.flush()
    p = Product(
        name="P",
        stock_qty=5,
        cost_price=3.5,
        selling_price=10,
        is_active=True,
    )
    db.add(p)
    db.flush()
    sale = Sale(
        cashier_id=u.id,
        subtotal=10,
        discount_total=0,
        total=10,
    )
    db.add(sale)
    db.flush()
    db.add(
        SaleItem(
            sale_id=sale.id,
            product_id=p.id,
            quantity=1,
            unit_price=10,
            discount=0,
            line_total=10,
            unit_cost=None,
        )
    )
    db.add(StoreSettings(store_name="S"))
    db.add(
        Withdrawal(
            cashier_id=u.id,
            amount=5,
            reason="Bank deposit",
            purpose=None,
        )
    )
    db.commit()
    db.close()

    with eng.begin() as conn:
        conn.execute(text("UPDATE withdrawals SET purpose = NULL"))
        conn.execute(text("UPDATE sale_items SET unit_cost = NULL"))

    report = ensure_financial_accuracy_schema(eng, create_missing_tables=False)
    assert report["backfilled_unit_cost_rows"] >= 1

    with eng.connect() as conn:
        uc = conn.execute(text("SELECT unit_cost FROM sale_items LIMIT 1")).scalar()
        pur = conn.execute(text("SELECT purpose FROM withdrawals LIMIT 1")).scalar()
    assert float(uc) == 3.5
    assert pur == "bank_deposit"
