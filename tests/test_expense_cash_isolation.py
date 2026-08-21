"""Expense vs cash vs withdrawal isolation — no double counting; lifecycle + tenants."""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-only-jwt-secret-key-do-not-use-in-prod-64b",
)

from app import auth as auth_mod
from app.database import Base, get_db
from app.main import app
from app.models import CashMovement, Expense, User, Withdrawal
from app.quotation_models import Tenant
from app.withdrawal_purpose import EXPENSE_PAYMENT, OWNER_DRAW, BANK_DEPOSIT


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


def _admin(db, *, username="iso_admin", tenant_id=None):
    u = User(
        username=username,
        email=f"{username}@example.com",
        full_name="Admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
        tenant_id=tenant_id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _tok(client, username="iso_admin"):
    return client.post(
        "/api/auth/token",
        data={"username": username, "password": "AdminPass1234"},
    ).json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _overview(client, tok):
    return client.get("/api/overview/summary", headers=_auth(tok)).json()


def test_cash_expense_reduces_profit_and_cash_once(client, db_session):
    _admin(db_session)
    tok = _tok(client)
    r = client.post(
        "/api/expenses",
        headers=_auth(tok),
        json={
            "amount": 50,
            "category": "rent",
            "description": "Shop rent cash",
            "payment_method": "cash",
            "auto_approve": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["cash_movement_id"] is not None

    # Exactly one CashMovement; zero Withdrawals created
    assert db_session.query(CashMovement).count() == 1
    assert db_session.query(Withdrawal).count() == 0

    ov = _overview(client, tok)
    assert ov["summary"]["expenses"] == 50.0
    assert ov["summary"]["net_profit"] == -50.0
    assert ov["summary"]["cash_on_hand"] == -50.0
    assert ov["summary"]["cash_expense_outflows"] == 50.0
    # Not reduced by $100
    assert ov["summary"]["cash_on_hand"] != -100.0


def test_bank_expense_reduces_profit_not_cash(client, db_session):
    _admin(db_session)
    tok = _tok(client)
    r = client.post(
        "/api/expenses",
        headers=_auth(tok),
        json={
            "amount": 50,
            "category": "utilities",
            "description": "Power bill bank",
            "payment_method": "bank_transfer",
            "auto_approve": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["cash_movement_id"] is None
    assert db_session.query(CashMovement).count() == 0
    assert db_session.query(Withdrawal).count() == 0

    ov = _overview(client, tok)
    assert ov["summary"]["expenses"] == 50.0
    assert ov["summary"]["net_profit"] == -50.0
    assert ov["summary"]["cash_on_hand"] == 0.0
    assert ov["summary"]["cash_expense_outflows"] == 0.0


def test_owner_draw_reduces_cash_not_profit(client, db_session):
    admin = _admin(db_session)
    tok = _tok(client)
    client.post(
        "/api/withdrawals",
        headers=_auth(tok),
        json={
            "amount": 50,
            "reason": "Owner draw",
            "purpose": OWNER_DRAW,
        },
    )
    ov = _overview(client, tok)
    assert ov["summary"]["expenses"] == 0.0
    assert ov["summary"]["net_profit"] == 0.0
    assert ov["summary"]["cash_on_hand"] == -50.0
    assert db_session.query(Expense).count() == 0


def test_bank_deposit_reduces_till_cash_not_profit(client, db_session):
    _admin(db_session)
    tok = _tok(client)
    client.post(
        "/api/withdrawals",
        headers=_auth(tok),
        json={
            "amount": 50,
            "reason": "Bank deposit",
            "purpose": BANK_DEPOSIT,
        },
    )
    ov = _overview(client, tok)
    assert ov["summary"]["expenses"] == 0.0
    assert ov["summary"]["net_profit"] == 0.0
    assert ov["summary"]["cash_on_hand"] == -50.0
    assert db_session.query(Expense).count() == 0


def test_expense_payment_withdrawal_alone_not_an_expense(client, db_session):
    _admin(db_session)
    tok = _tok(client)
    r = client.post(
        "/api/withdrawals",
        headers=_auth(tok),
        json={
            "amount": 50,
            "reason": "Expense payment",
            "purpose": EXPENSE_PAYMENT,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["purpose"] == EXPENSE_PAYMENT
    assert db_session.query(Expense).count() == 0
    assert db_session.query(CashMovement).filter(CashMovement.source_type == "expense").count() == 0

    ov = _overview(client, tok)
    assert ov["summary"]["expenses"] == 0.0
    assert ov["summary"]["cash_on_hand"] == -50.0  # via Withdrawal only


def test_cross_tenant_expense_excluded(client, db_session):
    t1 = Tenant(tenant_uid="iso-t1", name="A")
    t2 = Tenant(tenant_uid="iso-t2", name="B")
    db_session.add_all([t1, t2])
    db_session.flush()
    _admin(db_session, username="iso_a", tenant_id=t1.id)
    _admin(db_session, username="iso_b", tenant_id=t2.id)

    tok_b = _tok(client, "iso_b")
    client.post(
        "/api/expenses",
        headers=_auth(tok_b),
        json={
            "amount": 50,
            "category": "rent",
            "description": "B rent",
            "payment_method": "cash",
            "auto_approve": True,
        },
    )

    tok_a = _tok(client, "iso_a")
    ov = _overview(client, tok_a)
    assert ov["summary"]["expenses"] == 0.0
    assert ov["summary"]["cash_on_hand"] == 0.0


def test_approve_idempotent_no_double_cash(client, db_session):
    _admin(db_session)
    tok = _tok(client)
    created = client.post(
        "/api/expenses",
        headers=_auth(tok),
        json={
            "amount": 50,
            "category": "rent",
            "description": "Idempotent",
            "payment_method": "cash",
            "auto_approve": False,
        },
    ).json()
    assert created["status"] == "draft"
    eid = created["id"]

    a1 = client.post(f"/api/expenses/{eid}/approve", headers=_auth(tok), json={})
    a2 = client.post(f"/api/expenses/{eid}/approve", headers=_auth(tok), json={})
    assert a1.status_code == 200 and a2.status_code == 200
    assert db_session.query(CashMovement).count() == 1

    ov = _overview(client, tok)
    assert ov["summary"]["cash_on_hand"] == -50.0
    assert ov["summary"]["expenses"] == 50.0


def test_void_approved_cash_expense_restores_cash_and_profit(client, db_session):
    _admin(db_session)
    tok = _tok(client)
    eid = client.post(
        "/api/expenses",
        headers=_auth(tok),
        json={
            "amount": 50,
            "category": "rent",
            "description": "To void",
            "payment_method": "cash",
            "auto_approve": True,
        },
    ).json()["id"]

    before = _overview(client, tok)
    assert before["summary"]["cash_on_hand"] == -50.0
    assert before["summary"]["expenses"] == 50.0

    v = client.post(
        f"/api/expenses/{eid}/void",
        headers=_auth(tok),
        json={"reason": "entered wrong"},
    )
    assert v.status_code == 200, v.text
    assert v.json()["status"] == "voided"
    # Movement row retained for audit
    assert db_session.query(CashMovement).count() == 1

    after = _overview(client, tok)
    assert after["summary"]["expenses"] == 0.0
    assert after["summary"]["cash_on_hand"] == 0.0
    assert after["summary"]["cash_expense_outflows"] == 0.0

    # Idempotent void
    v2 = client.post(f"/api/expenses/{eid}/void", headers=_auth(tok), json={})
    assert v2.status_code == 200
    assert v2.json()["status"] == "voided"


def test_cannot_approve_voided(client, db_session):
    _admin(db_session)
    tok = _tok(client)
    eid = client.post(
        "/api/expenses",
        headers=_auth(tok),
        json={
            "amount": 10,
            "category": "other",
            "description": "x",
            "payment_method": "cash",
            "auto_approve": True,
        },
    ).json()["id"]
    client.post(f"/api/expenses/{eid}/void", headers=_auth(tok), json={})
    bad = client.post(f"/api/expenses/{eid}/approve", headers=_auth(tok), json={})
    assert bad.status_code == 400
