"""
Form login (/api/auth/token) must issue a refresh token so Android cashiers
can renew JWTs after the 8h access expiry and drain offline sales.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth as auth_mod
from app.branch_models import UserBranch
from app.database import Base, get_db
from app.enterprise_models import Branch
from app.inventory_service import get_branch_stock, seed_main_branch_from_legacy
from app.main import app as fastapi_app
from app.models import Product, Sale, User
from app.quotation_models import Tenant

import app.accounting_models  # noqa: F401
import app.branch_models  # noqa: F401
import app.enterprise_models  # noqa: F401


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

    fastapi_app.dependency_overrides[get_db] = _override
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


def _hash(pw="CashPass1234"):
    return auth_mod.get_password_hash(pw)


def _seed_cashier(db, *, stock=10):
    t = Tenant(tenant_uid=str(uuid.uuid4()), name="OAuth Refresh Shop")
    db.add(t)
    db.flush()
    main = Branch(
        tenant_id=t.id,
        name="Main Branch",
        code="MAIN",
        is_default=True,
        is_active=True,
    )
    db.add(main)
    db.flush()
    cash = User(
        username="oauth_cash",
        email="oauth_cash@example.com",
        password_hash=_hash(),
        role="cashier",
        tenant_id=t.id,
        branch_id=main.id,
        is_active=True,
    )
    db.add(cash)
    db.flush()
    db.add(
        UserBranch(
            tenant_id=t.id,
            user_id=cash.id,
            branch_id=main.id,
            is_default=True,
            is_active=True,
        )
    )
    p = Product(
        name="OAuth Widget",
        barcode="OAUTH-W1",
        cost_price=1,
        selling_price=5,
        stock_qty=stock,
        tenant_id=t.id,
        is_active=True,
    )
    db.add(p)
    db.flush()
    seed_main_branch_from_legacy(db, tenant_id=t.id, branch_id=main.id, product=p)
    db.commit()
    return t, main, cash, p


def test_form_login_returns_refresh_token(client, db_session):
    _seed_cashier(db_session)
    r = client.post(
        "/api/auth/token",
        data={"username": "oauth_cash", "password": "CashPass1234"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("access_token")
    assert body.get("refresh_token"), "Android offline sync requires refresh_token"
    assert body.get("expires_in") == auth_mod.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_refresh_then_sale_deducts_stock(client, db_session):
    t, main, cash, p = _seed_cashier(db_session, stock=10)
    login = client.post(
        "/api/auth/token",
        data={"username": "oauth_cash", "password": "CashPass1234"},
    ).json()
    refresh = login["refresh_token"]
    refreshed = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert refreshed.status_code == 200, refreshed.text
    token = refreshed.json()["access_token"]
    # Branch claim must survive refresh for create_sale without X-Branch-Id
    import base64
    import json

    payload = token.split(".")[1] + "=" * (-len(token.split(".")[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))
    assert claims.get("bid") == main.id

    before = get_branch_stock(db_session, main.id, p.id).quantity_on_hand
    sale = client.post(
        "/api/sales",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "items": [
                {"product_id": p.id, "quantity": 2, "unit_price": 5, "discount": 0},
            ],
            "payments": [{"method": "cash", "amount": 10}],
            "collection_status": "collected",
            "client_sale_id": "oauth-offline-1",
        },
    )
    assert sale.status_code == 200, sale.text
    after = get_branch_stock(db_session, main.id, p.id).quantity_on_hand
    assert after == before - Decimal("2.0000")
    # Idempotent retry (lost response)
    again = client.post(
        "/api/sales",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "items": [
                {"product_id": p.id, "quantity": 2, "unit_price": 5, "discount": 0},
            ],
            "payments": [{"method": "cash", "amount": 10}],
            "collection_status": "collected",
            "client_sale_id": "oauth-offline-1",
        },
    )
    assert again.status_code == 200
    assert again.json()["id"] == sale.json()["id"]
    assert get_branch_stock(db_session, main.id, p.id).quantity_on_hand == after
    assert db_session.query(Sale).filter(Sale.client_sale_id == "oauth-offline-1").count() == 1
