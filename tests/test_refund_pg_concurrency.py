"""
PostgreSQL concurrency checks for refund approval.

Skipped unless ``TEST_DATABASE_URL`` points at a PostgreSQL database.

Run:
  TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost/pos_test \\
    .venv/bin/python -m pytest tests/test_refund_pg_concurrency.py -v
"""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-only-jwt-secret-key-do-not-use-in-prod-64b",
)

pg_url = (os.environ.get("TEST_DATABASE_URL") or "").strip()
pytestmark = pytest.mark.skipif(
    not pg_url.startswith("postgresql"),
    reason="TEST_DATABASE_URL PostgreSQL not configured (Section 7/8 environment limitation)",
)

from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    InventoryMovement,
    Payment,
    Product,
    Refund,
    Sale,
    SaleItem,
    User,
)
from app.accounting_models import JournalEntry  # noqa: E402
from app.accounting_setup import initialize_chart_of_accounts  # noqa: E402
from app import auth as auth_mod  # noqa: E402
from app.refund_service import (  # noqa: E402
    RefundLineInput,
    approve_refund,
    create_refund,
)


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(pg_url, future=True, pool_size=5, max_overflow=5)
    import app.accounting_models  # noqa: F401
    import app.quotation_models  # noqa: F401

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def SessionLocal(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, future=True)


def _seed(db):
    admin = User(
        username=f"pg_admin_{os.getpid()}",
        email=f"pg_admin_{os.getpid()}@ex.com",
        password_hash=auth_mod.get_password_hash("AdminPass1234"),
        role="admin",
        is_active=True,
        full_name="A",
    )
    cash = User(
        username=f"pg_cash_{os.getpid()}",
        email=f"pg_cash_{os.getpid()}@ex.com",
        password_hash=auth_mod.get_password_hash("CashPass1234"),
        role="cashier",
        is_active=True,
        full_name="C",
    )
    db.add_all([admin, cash])
    db.commit()
    db.refresh(admin)
    db.refresh(cash)
    return admin, cash


def _sale(db, cash, qty=5):
    p = Product(
        name="PGWidget",
        stock_qty=10,
        cost_price=Decimal("4"),
        selling_price=Decimal("10"),
        is_active=True,
    )
    db.add(p)
    db.flush()
    sale = Sale(
        cashier_id=cash.id,
        subtotal=Decimal(qty * 10),
        discount_total=0,
        total=Decimal(qty * 10),
        created_at=datetime.utcnow(),
    )
    db.add(sale)
    db.flush()
    si = SaleItem(
        sale_id=sale.id,
        product_id=p.id,
        quantity=qty,
        unit_price=Decimal("10"),
        discount=0,
        line_total=Decimal(qty * 10),
        unit_cost=Decimal("4"),
    )
    db.add(si)
    db.add(Payment(sale_id=sale.id, method="cash", amount=Decimal(qty * 10)))
    db.commit()
    db.refresh(sale)
    db.refresh(si)
    db.refresh(p)
    return p, sale, si


def test_concurrent_overlapping_approvals_one_wins(SessionLocal, pg_engine):
    initialize_chart_of_accounts(SessionLocal())
    db = SessionLocal()
    admin, cash = _seed(db)
    p, sale, si = _sale(db, cash, qty=5)
    a = create_refund(
        db,
        cash,
        sale_id=sale.id,
        reason="A",
        refund_method="cash",
        items=[RefundLineInput(si.id, 3)],
    )
    b = create_refund(
        db,
        cash,
        sale_id=sale.id,
        reason="B",
        refund_method="cash",
        items=[RefundLineInput(si.id, 3)],
    )
    a_id, b_id, admin_id = a.id, b.id, admin.id
    product_id = p.id
    sale_id = sale.id
    db.close()

    def _approve(rid: int):
        s = SessionLocal()
        try:
            user = s.get(User, admin_id)
            return approve_refund(s, user, rid).status, None
        except Exception as e:
            return None, getattr(e, "status_code", type(e).__name__)
        finally:
            s.close()

    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(_approve, a_id), pool.submit(_approve, b_id)]
        for f in as_completed(futs):
            results.append(f.result())

    statuses = [r[0] for r in results]
    assert statuses.count("approved") == 1
    assert any(code in (400, 409) for _, code in results if code is not None)

    db = SessionLocal()
    approved = (
        db.query(Refund).filter(Refund.id.in_([a_id, b_id]), Refund.status == "approved").all()
    )
    assert len(approved) == 1
    from app.models import RefundItem

    aq = (
        db.query(func.coalesce(func.sum(RefundItem.quantity), 0))
        .join(Refund, Refund.id == RefundItem.refund_id)
        .filter(Refund.sale_id == sale_id, Refund.status == "approved")
        .scalar()
    )
    assert int(aq) <= 5
    stock = float(db.get(Product, product_id).stock_qty)
    assert stock == 10 + int(aq)
    je = (
        db.query(func.count(JournalEntry.id))
        .filter(
            JournalEntry.reference_type == "REFUND",
            JournalEntry.reference_id == approved[0].id,
        )
        .scalar()
    )
    assert je == 1
    db.close()


def test_concurrent_double_approve_same_refund(SessionLocal):
    db = SessionLocal()
    admin, cash = _seed(db)
    p, sale, si = _sale(db, cash, qty=2)
    refund = create_refund(
        db,
        cash,
        sale_id=sale.id,
        reason="once",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    rid, admin_id, stock0 = refund.id, admin.id, float(p.stock_qty)
    db.close()

    def _approve():
        s = SessionLocal()
        try:
            user = s.get(User, admin_id)
            return approve_refund(s, user, rid).status, None
        except Exception as e:
            return None, getattr(e, "status_code", type(e).__name__)
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result() for f in as_completed([pool.submit(_approve), pool.submit(_approve)])]

    assert sum(1 for st, _ in results if st == "approved") == 1
    assert any(code in (400, 409) for _, code in results if code is not None)

    db = SessionLocal()
    r = db.get(Refund, rid)
    assert r.status == "approved"
    moves = (
        db.query(InventoryMovement)
        .filter(InventoryMovement.reason == f"Refund {r.refund_number}")
        .count()
    )
    assert moves == 1
    assert float(db.get(Product, p.id).stock_qty) == stock0 + 1
    je = (
        db.query(func.count(JournalEntry.id))
        .filter(JournalEntry.reference_type == "REFUND", JournalEntry.reference_id == rid)
        .scalar()
    )
    assert je == 1
    db.close()
