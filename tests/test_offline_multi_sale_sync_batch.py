"""
Simulates Android offline multi-sale drain after reconnect:
three client_sale_id uploads → stock 10→5, idempotent re-drain no double deduct.
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
from app.models import InventoryMovement, Product, Sale, User
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


def _seed(db, stock=10):
    t = Tenant(tenant_uid=str(uuid.uuid4()), name="Offline Batch Shop")
    db.add(t)
    db.flush()
    main = Branch(
        tenant_id=t.id, name="Main Branch", code="MAIN", is_default=True, is_active=True
    )
    db.add(main)
    db.flush()
    cash = User(
        username="batch_cash",
        email="batch_cash@example.com",
        password_hash=auth_mod.get_password_hash("CashPass1234"),
        role="cashier",
        tenant_id=t.id,
        branch_id=main.id,
        is_active=True,
    )
    db.add(cash)
    db.flush()
    db.add(
        UserBranch(
            tenant_id=t.id, user_id=cash.id, branch_id=main.id, is_default=True, is_active=True
        )
    )
    p = Product(
        name="Batch Widget",
        barcode="BATCH-W1",
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
    return main, p


def _login(client):
    r = client.post(
        "/api/auth/token", data={"username": "batch_cash", "password": "CashPass1234"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("refresh_token"), "refresh required for 3-day offline reconnect"
    return body["access_token"], body["refresh_token"]


def _sale(client, tok, pid, qty, csid):
    return client.post(
        "/api/sales",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "items": [{"product_id": pid, "quantity": qty, "unit_price": 5, "discount": 0}],
            "payments": [{"method": "cash", "amount": 5 * qty}],
            "collection_status": "collected",
            "client_sale_id": csid,
        },
    )


def test_three_offline_sales_then_reconnect_batch(client, db_session):
    main, p = _seed(db_session, stock=10)
    tok, refresh = _login(client)
    assert get_branch_stock(db_session, main.id, p.id).quantity_on_hand == Decimal("10.0000")

    # Simulate Android local queue of 3 sales uploaded after reconnect
    queued = [
        ("off-day1-a", 2),
        ("off-day2-b", 1),
        ("off-day3-c", 2),
    ]
    sale_ids = []
    for csid, qty in queued:
        r = _sale(client, tok, p.id, qty, csid)
        assert r.status_code == 200, r.text
        sale_ids.append(r.json()["id"])

    db_session.expire_all()
    assert get_branch_stock(db_session, main.id, p.id).quantity_on_hand == Decimal("5.0000")

    # Second Sync / lost-response retries — no further deduction
    for csid, qty in queued:
        r = _sale(client, tok, p.id, qty, csid)
        assert r.status_code == 200, r.text
    db_session.expire_all()
    assert get_branch_stock(db_session, main.id, p.id).quantity_on_hand == Decimal("5.0000")
    assert db_session.query(Sale).filter(Sale.client_sale_id.in_([c for c, _ in queued])).count() == 3

    neg = (
        db_session.query(InventoryMovement)
        .filter(InventoryMovement.product_id == p.id, InventoryMovement.change_qty < 0)
        .count()
    )
    assert neg == 3

    # Auth refresh still allows drain (Day 4 reconnect)
    refreshed = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert refreshed.status_code == 200, refreshed.text
    tok2 = refreshed.json()["access_token"]
    listed = client.get("/api/products", headers={"Authorization": f"Bearer {tok2}"})
    assert listed.status_code == 200
    row = next(x for x in listed.json() if x["id"] == p.id)
    assert float(row["stock_qty"]) == 5.0
