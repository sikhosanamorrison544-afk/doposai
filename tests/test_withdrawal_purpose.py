"""Withdrawal purpose classification — not every cash removal is an owner drawing."""
from __future__ import annotations

import os
from datetime import datetime
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
from app.accounting_engine import AccountingEngine
from app.accounting_setup import initialize_chart_of_accounts
from app.database import Base, get_db
from app.main import app
from app.models import User, Withdrawal
from app.withdrawal_purpose import (
    BANK_DEPOSIT,
    EXPENSE_PAYMENT,
    OWNER_DRAW,
    UNCLASSIFIED,
    debit_account_for_purpose,
    purpose_from_reason,
    resolve_purpose,
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


def test_purpose_from_legacy_reasons():
    assert purpose_from_reason("Daily expenses") == EXPENSE_PAYMENT
    assert purpose_from_reason("Salary") == EXPENSE_PAYMENT
    assert purpose_from_reason("Bank deposit") == BANK_DEPOSIT
    assert purpose_from_reason("Owner draw") == OWNER_DRAW
    assert purpose_from_reason("Mystery cash out") == "other"
    assert purpose_from_reason(None) == UNCLASSIFIED
    # Must not invent owner_draw for unknown
    assert purpose_from_reason("Daily expenses") != OWNER_DRAW


def test_resolve_purpose_explicit_wins():
    assert resolve_purpose(purpose="bank_deposit", reason="Salary") == BANK_DEPOSIT
    assert resolve_purpose(purpose=None, reason="Salary") == EXPENSE_PAYMENT


def test_debit_accounts_by_purpose():
    assert debit_account_for_purpose(OWNER_DRAW) == "3300"
    assert debit_account_for_purpose(BANK_DEPOSIT) == "1020"
    assert debit_account_for_purpose(EXPENSE_PAYMENT) == "1450"
    assert debit_account_for_purpose(UNCLASSIFIED) == "1450"


def test_post_withdrawal_bank_deposit_not_drawings(db_session):
    initialize_chart_of_accounts(db_session)
    admin = User(
        username="wd_admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
        full_name="A",
    )
    db_session.add(admin)
    db_session.flush()
    w = Withdrawal(
        cashier_id=admin.id,
        amount=Decimal("100.00"),
        reason="Bank deposit",
        purpose=BANK_DEPOSIT,
        created_at=datetime.utcnow(),
    )
    db_session.add(w)
    db_session.flush()
    je = AccountingEngine(db_session).post_withdrawal(w)
    codes = sorted(
        (line.account.code, float(line.debit_amount), float(line.credit_amount))
        for line in je.lines
    )
    # Dr Bank 1020, Cr Cash 1000 — not 3300
    assert any(c[0] == "1020" and c[1] == 100.0 for c in codes)
    assert any(c[0] == "1000" and c[2] == 100.0 for c in codes)
    assert not any(c[0] == "3300" for c in codes)


def test_post_withdrawal_owner_draw_uses_3300(db_session):
    initialize_chart_of_accounts(db_session)
    admin = User(
        username="wd_admin2",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.flush()
    w = Withdrawal(
        cashier_id=admin.id,
        amount=Decimal("25.00"),
        reason="Owner draw",
        purpose=OWNER_DRAW,
        created_at=datetime.utcnow(),
    )
    db_session.add(w)
    db_session.flush()
    je = AccountingEngine(db_session).post_withdrawal(w)
    assert any(line.account.code == "3300" and float(line.debit_amount) == 25.0 for line in je.lines)


def test_create_withdrawal_api_sets_purpose(client, db_session):
    admin = User(
        username="wd_api_admin",
        email="w@example.com",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
        full_name="Admin",
    )
    db_session.add(admin)
    db_session.commit()
    tok = client.post(
        "/api/auth/token",
        data={"username": "wd_api_admin", "password": "AdminPass1234"},
    ).json()["access_token"]
    r = client.post(
        "/api/withdrawals",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "amount": 40,
            "reason": "Bank deposit",
            "purpose": "bank_deposit",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["purpose"] == "bank_deposit"
    assert data["reason"] == "Bank deposit"
    # Still reduces cash activity / not P&L expense
    ov = client.get(
        "/api/overview/summary",
        headers={"Authorization": f"Bearer {tok}"},
    ).json()
    assert ov["summary"]["expenses"] == 0.0
    assert ov["summary"]["cash_on_hand"] == -40.0


def test_legacy_daily_expenses_infer_expense_payment_not_drawings(db_session):
    initialize_chart_of_accounts(db_session)
    admin = User(
        username="wd_legacy",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.flush()
    w = Withdrawal(
        cashier_id=admin.id,
        amount=Decimal("10.00"),
        reason="Daily expenses",
        purpose=None,  # infer
        created_at=datetime.utcnow(),
    )
    db_session.add(w)
    db_session.flush()
    je = AccountingEngine(db_session).post_withdrawal(w)
    assert w.purpose == EXPENSE_PAYMENT
    codes = [line.account.code for line in je.lines]
    assert "1450" in codes
    assert "3300" not in codes
    # Must not hit P&L operating expense accounts
    assert not any(c.startswith("6") for c in codes)


def test_backfill_never_invents_owner_draw(db_session):
    from sqlalchemy import text

    from app.main import _backfill_withdrawal_purposes

    admin = User(
        username="wd_bf",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.flush()
    db_session.add_all(
        [
            Withdrawal(
                cashier_id=admin.id,
                amount=Decimal("1"),
                reason="Daily expenses",
                purpose=None,
            ),
            Withdrawal(
                cashier_id=admin.id,
                amount=Decimal("2"),
                reason="Weird till scoop",
                purpose=None,
            ),
            Withdrawal(
                cashier_id=admin.id,
                amount=Decimal("3"),
                reason="Owner draw",
                purpose=None,
            ),
        ]
    )
    db_session.commit()
    with db_session.bind.connect() as conn:
        with conn.begin():
            _backfill_withdrawal_purposes(conn)
    rows = {
        w.reason: w.purpose
        for w in db_session.query(Withdrawal).all()
    }
    # expire cache
    db_session.expire_all()
    rows = {
        w.reason: w.purpose
        for w in db_session.query(Withdrawal).all()
    }
    assert rows["Daily expenses"] == EXPENSE_PAYMENT
    assert rows["Weird till scoop"] == UNCLASSIFIED
    assert rows["Owner draw"] == OWNER_DRAW
    assert rows["Weird till scoop"] != OWNER_DRAW
