"""Section 3 — refund-aware revenue/profit uses SaleItem.unit_cost + approval date."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-only-jwt-secret-key-do-not-use-in-prod-64b",
)

from app import auth as auth_mod
from app.database import Base, get_db
from app.finance_service import refund_aware_gross_profit, unit_cost_expr
from app.main import app
from app.models import Payment, Product, Refund, RefundItem, Sale, SaleItem, User


@pytest.fixture()
def db_session():
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
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session):
    def _override():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _hash(pw: str) -> str:
    return auth_mod.get_password_hash(pw)


def _seed(db):
    admin = User(
        username="rf_admin",
        email="rf@example.com",
        full_name="A",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
    )
    cashier = User(
        username="rf_cash",
        email="rfc@example.com",
        full_name="C",
        password_hash=_hash("CashPass1234"),
        role="cashier",
        is_active=True,
    )
    db.add_all([admin, cashier])
    db.commit()
    db.refresh(admin)
    db.refresh(cashier)
    return admin, cashier


def _tok(client):
    return client.post(
        "/api/auth/token",
        data={"username": "rf_admin", "password": "AdminPass1234"},
    ).json()["access_token"]


def test_unit_cost_expr_prefers_snapshot(db_session):
    from sqlalchemy import select

    _seed(db_session)
    p = Product(
        name="P",
        stock_qty=10,
        cost_price=Decimal("9.00"),
        selling_price=Decimal("20"),
        is_active=True,
    )
    db_session.add(p)
    db_session.flush()
    admin, cash = db_session.query(User).filter_by(username="rf_admin").one(), db_session.query(User).filter_by(username="rf_cash").one()
    sale = Sale(
        cashier_id=cash.id,
        subtotal=Decimal("20"),
        discount_total=0,
        total=Decimal("20"),
        created_at=datetime.utcnow(),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=p.id,
            quantity=1,
            unit_price=Decimal("20"),
            discount=0,
            line_total=Decimal("20"),
            unit_cost=Decimal("2.00"),
        )
    )
    db_session.commit()
    # Live cost changed after sale
    p.cost_price = Decimal("9.00")
    db_session.commit()
    start = datetime.utcnow() - timedelta(days=1)
    end = datetime.utcnow() + timedelta(days=1)
    gp = refund_aware_gross_profit(
        db_session, admin, start, end, branch_id=None
    )
    assert gp == Decimal("18.00")  # 20 - 2, not 20 - 9


def test_partial_refund_item_reverses_historical_margin(client, db_session):
    admin, cash = _seed(db_session)
    p = Product(
        name="Widget",
        stock_qty=10,
        cost_price=Decimal("99"),  # live cost should be ignored
        selling_price=Decimal("10"),
        is_active=True,
    )
    db_session.add(p)
    db_session.flush()
    sale = Sale(
        cashier_id=cash.id,
        subtotal=Decimal("20"),
        discount_total=0,
        total=Decimal("20"),
        created_at=datetime.utcnow(),
    )
    db_session.add(sale)
    db_session.flush()
    si = SaleItem(
        sale_id=sale.id,
        product_id=p.id,
        quantity=2,
        unit_price=Decimal("10"),
        discount=0,
        line_total=Decimal("20"),
        unit_cost=Decimal("4.00"),
    )
    db_session.add(si)
    db_session.add(Payment(sale_id=sale.id, method="cash", amount=Decimal("20")))
    db_session.flush()
    # Refund 1 of 2 units
    refund = Refund(
        sale_id=sale.id,
        refund_number="RF-UNIT-1",
        amount=Decimal("10"),
        status="approved",
        reason="partial",
        refund_type="partial",
        refund_method="cash",
        created_at=datetime.utcnow() - timedelta(days=5),
        approved_at=datetime.utcnow(),
        requested_by_id=cash.id,
        approved_by_id=admin.id,
    )
    db_session.add(refund)
    db_session.flush()
    db_session.add(
        RefundItem(
            refund_id=refund.id,
            sale_item_id=si.id,
            product_id=p.id,
            quantity=1,
            unit_price=Decimal("10"),
            discount=0,
            line_total=Decimal("10"),
        )
    )
    db_session.commit()

    tok = _tok(client)
    ov = client.get(
        "/api/overview/summary",
        headers={"Authorization": f"Bearer {tok}"},
    ).json()
    # Sale margin 20-8=12; refund margin 10-4=6 → GP 6
    assert ov["summary"]["gross_profit"] == 6.0
    assert ov["summary"]["revenue"] == 10.0
    assert ov["summary"]["refunds"] == 10.0
    assert ov["summary"]["cash_on_hand"] == 10.0  # 20 cash - 10 cash refund


def test_refund_attributed_to_approval_date_not_request(client, db_session):
    admin, cash = _seed(db_session)
    p = Product(
        name="G",
        stock_qty=5,
        cost_price=Decimal("1"),
        selling_price=Decimal("5"),
        is_active=True,
    )
    db_session.add(p)
    db_session.flush()
    # Sale today
    sale = Sale(
        cashier_id=cash.id,
        subtotal=Decimal("5"),
        discount_total=0,
        total=Decimal("5"),
        created_at=datetime.utcnow(),
    )
    db_session.add(sale)
    db_session.flush()
    si = SaleItem(
        sale_id=sale.id,
        product_id=p.id,
        quantity=1,
        unit_price=Decimal("5"),
        discount=0,
        line_total=Decimal("5"),
        unit_cost=Decimal("1"),
    )
    db_session.add(si)
    # Requested long ago, approved today
    refund = Refund(
        sale_id=sale.id,
        refund_number="RF-DATE-1",
        amount=Decimal("5"),
        status="approved",
        reason="late approve",
        refund_type="full",
        refund_method="cash",
        created_at=datetime.utcnow() - timedelta(days=40),
        approved_at=datetime.utcnow(),
        requested_by_id=cash.id,
        approved_by_id=admin.id,
    )
    db_session.add(refund)
    db_session.flush()
    db_session.add(
        RefundItem(
            refund_id=refund.id,
            sale_item_id=si.id,
            product_id=p.id,
            quantity=1,
            unit_price=Decimal("5"),
            discount=0,
            line_total=Decimal("5"),
        )
    )
    db_session.commit()

    tok = _tok(client)
    today = datetime.utcnow().date().isoformat()
    ov = client.get(
        "/api/overview/summary",
        params={"from_date": today, "to_date": today},
        headers={"Authorization": f"Bearer {tok}"},
    ).json()
    assert ov["summary"]["refunds"] == 5.0
    assert ov["summary"]["gross_profit"] == 0.0
    assert ov["summary"]["revenue"] == 0.0


def test_top_selling_uses_unit_cost(client, db_session):
    admin, cash = _seed(db_session)
    p = Product(
        name="Top",
        barcode="T1",
        stock_qty=10,
        cost_price=Decimal("50"),  # live — must not drive profit
        selling_price=Decimal("10"),
        is_active=True,
    )
    db_session.add(p)
    db_session.flush()
    sale = Sale(
        cashier_id=cash.id,
        subtotal=Decimal("10"),
        discount_total=0,
        total=Decimal("10"),
        created_at=datetime.utcnow() - timedelta(minutes=5),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=p.id,
            quantity=1,
            unit_price=Decimal("10"),
            discount=0,
            line_total=Decimal("10"),
            unit_cost=Decimal("3"),
        )
    )
    db_session.commit()
    tok = _tok(client)
    r = client.get(
        "/api/analytics/top-selling",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    assert float(r.json()["total_profit"]) == 7.0  # 10 - 3, not 10 - 50
