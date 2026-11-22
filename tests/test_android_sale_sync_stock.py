"""
Android sale sync → stock deduction (same POST /api/sales as the app).

Covers:
- Online-style create with client_sale_id deducts stock + movement immediately
- Multi-qty and multi-product
- Duplicate sync is idempotent (one sale, one deduction)
- Tenant/branch isolation
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
from app.enterprise_models import Branch, BranchProductStock
from app.inventory_service import get_branch_stock, seed_main_branch_from_legacy, to_qty
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


def _hash(pw="AdminPass1234"):
    return auth_mod.get_password_hash(pw)


def _seed_cashier(db, *, stock_a=10, stock_b=20):
    t = Tenant(tenant_uid=str(uuid.uuid4()), name="Android Sync Shop")
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
        username="and_cash",
        email="and_cash@example.com",
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
            role="cashier",
        )
    )
    pa = Product(
        name="Widget A",
        barcode="AND-A",
        selling_price=5,
        cost_price=2,
        stock_qty=stock_a,
        tenant_id=t.id,
        is_active=True,
    )
    pb = Product(
        name="Widget B",
        barcode="AND-B",
        selling_price=3,
        cost_price=1,
        stock_qty=stock_b,
        tenant_id=t.id,
        is_active=True,
    )
    db.add_all([pa, pb])
    db.flush()
    seed_main_branch_from_legacy(db, tenant_id=t.id, branch_id=main.id, product=pa)
    seed_main_branch_from_legacy(db, tenant_id=t.id, branch_id=main.id, product=pb)
    db.commit()
    return t, main, cash, pa, pb


def _login(client, username="and_cash", password="AdminPass1234"):
    r = client.post("/api/auth/token", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok, branch_id=None):
    h = {"Authorization": f"Bearer {tok}"}
    if branch_id is not None:
        h["X-Branch-Id"] = str(branch_id)
    return h


def _android_sale_payload(pa, pb=None, *, qty_a=2, qty_b=None, client_sale_id="android-uuid-1"):
    items = [
        {"product_id": pa.id, "quantity": qty_a, "unit_price": float(pa.selling_price), "discount": 0},
    ]
    total = float(pa.selling_price) * qty_a
    if pb is not None and qty_b:
        items.append(
            {
                "product_id": pb.id,
                "quantity": qty_b,
                "unit_price": float(pb.selling_price),
                "discount": 0,
            }
        )
        total += float(pb.selling_price) * qty_b
    return {
        "customer_id": None,
        "items": items,
        "payments": [{"method": "cash", "amount": total}],
        "notes": "",
        "collection_status": "collected",
        "client_sale_id": client_sale_id,
    }


def test_android_online_sale_deducts_stock_immediately(client, db_session):
    t, main, cash, pa, pb = _seed_cashier(db_session, stock_a=10)
    tok = _login(client)
    before = get_branch_stock(db_session, main.id, pa.id).quantity_on_hand
    assert before == Decimal("10.0000")

    payload = _android_sale_payload(pa, qty_a=2, client_sale_id="and-online-1")
    # Mirror Android: often omits X-Branch-Id; JWT branch_id still scopes sale.
    r = client.post("/api/sales", headers=_auth(tok), json=payload)
    assert r.status_code == 200, r.text
    sale_id = r.json()["id"]

    db_session.expire_all()
    after = get_branch_stock(db_session, main.id, pa.id).quantity_on_hand
    assert after == Decimal("8.0000")
    moves = (
        db_session.query(InventoryMovement)
        .filter(
            InventoryMovement.product_id == pa.id,
            InventoryMovement.branch_id == main.id,
        )
        .all()
    )
    sale_moves = [
        m for m in moves if float(m.change_qty) < 0 and f"#{sale_id}" in (m.reason or "")
    ]
    assert len(sale_moves) == 1
    assert to_qty(sale_moves[0].change_qty) == Decimal("-2.0000")


def test_android_multi_product_sale_deducts_each(client, db_session):
    t, main, cash, pa, pb = _seed_cashier(db_session, stock_a=10, stock_b=20)
    tok = _login(client)
    payload = _android_sale_payload(pa, pb, qty_a=2, qty_b=5, client_sale_id="and-multi-1")
    r = client.post("/api/sales", headers=_auth(tok, main.id), json=payload)
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert get_branch_stock(db_session, main.id, pa.id).quantity_on_hand == Decimal("8.0000")
    assert get_branch_stock(db_session, main.id, pb.id).quantity_on_hand == Decimal("15.0000")


def test_android_duplicate_sync_no_double_deduct(client, db_session):
    t, main, cash, pa, pb = _seed_cashier(db_session, stock_a=10)
    tok = _login(client)
    payload = _android_sale_payload(pa, qty_a=2, client_sale_id="and-dup-1")
    r1 = client.post("/api/sales", headers=_auth(tok, main.id), json=payload)
    r2 = client.post("/api/sales", headers=_auth(tok, main.id), json=payload)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["id"] == r2.json()["id"]
    db_session.expire_all()
    assert get_branch_stock(db_session, main.id, pa.id).quantity_on_hand == Decimal("8.0000")
    assert db_session.query(Sale).filter(Sale.client_sale_id == "and-dup-1").count() == 1
    neg = (
        db_session.query(InventoryMovement)
        .filter(
            InventoryMovement.product_id == pa.id,
            InventoryMovement.change_qty < 0,
        )
        .count()
    )
    assert neg == 1


def test_android_insufficient_stock_rolls_back_sale(client, db_session):
    t, main, cash, pa, pb = _seed_cashier(db_session, stock_a=1)
    tok = _login(client)
    payload = _android_sale_payload(pa, qty_a=3, client_sale_id="and-fail-1")
    r = client.post("/api/sales", headers=_auth(tok, main.id), json=payload)
    assert r.status_code == 400, r.text
    db_session.expire_all()
    assert get_branch_stock(db_session, main.id, pa.id).quantity_on_hand == Decimal("1.0000")
    assert db_session.query(Sale).filter(Sale.client_sale_id == "and-fail-1").count() == 0


def test_android_sale_does_not_touch_other_tenant_branch(client, db_session):
    t1, main1, cash1, pa1, _ = _seed_cashier(db_session, stock_a=10)
    t2 = Tenant(tenant_uid=str(uuid.uuid4()), name="Other Shop")
    db_session.add(t2)
    db_session.flush()
    main2 = Branch(
        tenant_id=t2.id,
        name="Main Branch",
        code="MAIN",
        is_default=True,
        is_active=True,
    )
    db_session.add(main2)
    db_session.flush()
    p2 = Product(
        name="Other Widget",
        barcode="OTHER-1",
        selling_price=5,
        cost_price=2,
        stock_qty=10,
        tenant_id=t2.id,
        is_active=True,
    )
    db_session.add(p2)
    db_session.flush()
    seed_main_branch_from_legacy(db_session, tenant_id=t2.id, branch_id=main2.id, product=p2)
    db_session.commit()

    tok = _login(client)
    payload = _android_sale_payload(pa1, qty_a=2, client_sale_id="and-iso-1")
    assert client.post("/api/sales", headers=_auth(tok, main1.id), json=payload).status_code == 200
    db_session.expire_all()
    assert get_branch_stock(db_session, main1.id, pa1.id).quantity_on_hand == Decimal("8.0000")
    assert get_branch_stock(db_session, main2.id, p2.id).quantity_on_hand == Decimal("10.0000")


def test_products_list_reflects_stock_after_android_sale(client, db_session):
    t, main, cash, pa, pb = _seed_cashier(db_session, stock_a=10)
    tok = _login(client)
    payload = _android_sale_payload(pa, qty_a=3, client_sale_id="and-list-1")
    assert client.post("/api/sales", headers=_auth(tok, main.id), json=payload).status_code == 200
    listed = client.get("/api/products", headers=_auth(tok, main.id))
    assert listed.status_code == 200, listed.text
    row = next(p for p in listed.json() if p["id"] == pa.id)
    assert float(row["stock_qty"]) == 7.0
