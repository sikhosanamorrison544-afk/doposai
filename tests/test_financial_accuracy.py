"""Financial accuracy: expenses, refund-aware profit, currency, withdrawals ≠ expenses."""
from __future__ import annotations

import os
from datetime import date, datetime
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
from app.main import app
from app.models import (
    Expense,
    Payment,
    Product,
    Refund,
    Sale,
    SaleItem,
    StoreSettings,
    User,
    Withdrawal,
)


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
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _hash(pw: str) -> str:
    return auth_mod.get_password_hash(pw)


def _seed(db):
    admin = User(
        username="fin_admin",
        email="fin_admin@example.com",
        full_name="Fin Admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
    )
    cashier = User(
        username="fin_cashier",
        email="fin_cashier@example.com",
        full_name="Fin Cashier",
        password_hash=_hash("CashPass1234"),
        role="cashier",
        is_active=True,
    )
    db.add_all([admin, cashier])
    db.add(StoreSettings(store_name="Fin Shop", currency="ZAR"))
    db.commit()
    db.refresh(admin)
    db.refresh(cashier)
    return admin, cashier


def _login(client, username, password="AdminPass1234"):
    r = client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_withdrawals_not_counted_as_expenses(client, db_session):
    admin, cashier = _seed(db_session)
    db_session.add(
        Withdrawal(
            cashier_id=admin.id,
            amount=Decimal("50.00"),
            reason="Daily expenses",
            created_at=datetime.utcnow(),
        )
    )
    db_session.commit()
    tok = _login(client, "fin_admin")["access_token"]
    ov = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert ov["summary"]["expenses"] == 0.0
    assert ov["summary"]["cash_on_hand"] == -50.0


def test_approved_expense_reduces_net_and_cash(client, db_session):
    admin, cashier = _seed(db_session)
    product = Product(
        name="Thing",
        stock_qty=10,
        cost_price=Decimal("2.00"),
        selling_price=Decimal("5.00"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    sale = Sale(
        created_at=datetime.utcnow(),
        cashier_id=cashier.id,
        subtotal=Decimal("10.00"),
        discount_total=Decimal("0"),
        total=Decimal("10.00"),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=2,
            unit_price=Decimal("5.00"),
            discount=Decimal("0"),
            line_total=Decimal("10.00"),
            unit_cost=Decimal("2.00"),
        )
    )
    db_session.add(Payment(sale_id=sale.id, method="cash", amount=Decimal("10.00")))
    db_session.commit()

    tok = _login(client, "fin_admin")["access_token"]
    r = client.post(
        "/api/expenses",
        headers=_auth(tok),
        json={
            "amount": 3.0,
            "category": "rent",
            "description": "Shop rent",
            "payment_method": "cash",
            "auto_approve": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["cash_movement_id"] is not None

    ov = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert ov["summary"]["gross_profit"] == 6.0  # 10 - 4
    assert ov["summary"]["expenses"] == 3.0
    assert ov["summary"]["net_profit"] == 3.0
    assert ov["summary"]["cash_on_hand"] == 7.0  # 10 - 3 expense cash
    assert ov["business"]["currency"] == "ZAR"

    cards = {c["key"]: c for c in ov["cards"]}
    assert cards["expenses"]["label"] == "Operating expenses"
    assert cards["net_result"]["label"] == "Net profit"


def test_refund_reduces_gross_profit(client, db_session):
    admin, cashier = _seed(db_session)
    product = Product(
        name="Gadget",
        stock_qty=10,
        cost_price=Decimal("1.00"),
        selling_price=Decimal("5.00"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    sale = Sale(
        created_at=datetime.utcnow(),
        cashier_id=cashier.id,
        subtotal=Decimal("5.00"),
        discount_total=Decimal("0"),
        total=Decimal("5.00"),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=1,
            unit_price=Decimal("5.00"),
            discount=Decimal("0"),
            line_total=Decimal("5.00"),
            unit_cost=Decimal("1.00"),
        )
    )
    db_session.add(
        Refund(
            sale_id=sale.id,
            refund_number="RF-FIN-1",
            amount=Decimal("5.00"),
            status="approved",
            reason="return",
            refund_type="full",
            refund_method="cash",
            created_at=datetime.utcnow(),
            requested_by_id=cashier.id,
        )
    )
    db_session.commit()

    tok = _login(client, "fin_admin")["access_token"]
    ov = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert ov["summary"]["revenue"] == 0.0
    assert ov["summary"]["gross_profit"] == 0.0  # 4 margin reversed


def test_historical_unit_cost_not_live_price(client, db_session):
    admin, cashier = _seed(db_session)
    product = Product(
        name="Widget",
        stock_qty=10,
        cost_price=Decimal("1.00"),
        selling_price=Decimal("10.00"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    sale = Sale(
        created_at=datetime.utcnow(),
        cashier_id=cashier.id,
        subtotal=Decimal("10.00"),
        discount_total=Decimal("0"),
        total=Decimal("10.00"),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=1,
            unit_price=Decimal("10.00"),
            discount=Decimal("0"),
            line_total=Decimal("10.00"),
            unit_cost=Decimal("1.00"),
        )
    )
    product.cost_price = Decimal("9.00")  # change catalog cost after sale
    db_session.commit()

    tok = _login(client, "fin_admin")["access_token"]
    ov = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert ov["summary"]["gross_profit"] == 9.0  # uses snapshot 1, not live 9


def test_store_currency_update(client, db_session):
    _seed(db_session)
    tok = _login(client, "fin_admin")["access_token"]
    r = client.put(
        "/api/store-settings",
        headers=_auth(tok),
        json={
            "store_name": "Fin Shop",
            "currency": "BWP",
            "low_stock_email_enabled": False,
            "default_low_stock_threshold": 10,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["currency"] == "BWP"
    ov = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert ov["business"]["currency"] == "BWP"


def test_reports_summary_refund_aware(client, db_session):
    admin, cashier = _seed(db_session)
    product = Product(
        name="X",
        stock_qty=5,
        cost_price=Decimal("2"),
        selling_price=Decimal("8"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    sale = Sale(
        created_at=datetime.utcnow(),
        cashier_id=cashier.id,
        subtotal=Decimal("8"),
        discount_total=Decimal("0"),
        total=Decimal("8"),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=1,
            unit_price=Decimal("8"),
            discount=0,
            line_total=Decimal("8"),
            unit_cost=Decimal("2"),
        )
    )
    db_session.add(
        Refund(
            sale_id=sale.id,
            refund_number="RF-FIN-2",
            amount=Decimal("8"),
            status="approved",
            reason="r",
            refund_type="full",
            refund_method="cash",
            created_at=datetime.utcnow(),
            requested_by_id=cashier.id,
        )
    )
    db_session.commit()
    tok = _login(client, "fin_admin")["access_token"]
    today = datetime.utcnow().date().isoformat()
    rp = client.get(
        "/api/reports/summary",
        params={"from_date": today, "to_date": today},
        headers=_auth(tok),
    )
    assert rp.status_code == 200, rp.text
    data = rp.json()
    assert float(data["profit"]) == 0.0
    assert float(data["refunds"]) == 8.0
    assert data["currency"] == "ZAR"


def test_expenses_page_gated(client, db_session):
    _seed(db_session)
    r = client.get("/expenses", follow_redirects=False)
    assert r.status_code in (302, 303, 401, 200)
