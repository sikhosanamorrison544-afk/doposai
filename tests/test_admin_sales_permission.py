"""
Admin POST /api/sales after Perm.SALES grant (Android offline sync recovery).
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
from app.permissions import Perm, has_permission
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


def _seed_admin_and_cashier(db, *, stock=10):
    t = Tenant(tenant_uid=str(uuid.uuid4()), name="Admin Sales Shop")
    db.add(t)
    db.flush()
    main = Branch(
        tenant_id=t.id,
        name="Main",
        code="MAIN",
        is_default=True,
        is_active=True,
    )
    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True)
    db.add_all([main, west])
    db.flush()
    admin = User(
        username="adm_sale",
        email="adm@example.com",
        password_hash=auth_mod.get_password_hash("AdminPass1234"),
        role="admin",
        tenant_id=t.id,
        branch_id=main.id,
        is_active=True,
    )
    cash = User(
        username="cash_sale",
        email="cash@example.com",
        password_hash=auth_mod.get_password_hash("CashPass1234"),
        role="cashier",
        tenant_id=t.id,
        branch_id=main.id,
        is_active=True,
    )
    db.add_all([admin, cash])
    db.flush()
    for u, br in [(admin, main), (cash, main)]:
        db.add(
            UserBranch(
                tenant_id=t.id,
                user_id=u.id,
                branch_id=br.id,
                is_default=True,
                is_active=True,
                role=u.role,
            )
        )
    p = Product(
        name="Admin Widget",
        barcode="ADM-W1",
        selling_price=5,
        cost_price=2,
        stock_qty=stock,
        tenant_id=t.id,
        is_active=True,
    )
    db.add(p)
    db.flush()
    seed_main_branch_from_legacy(db, tenant_id=t.id, branch_id=main.id, product=p)
    db.commit()
    return t, main, west, admin, cash, p


def _login(client, username, password):
    r = client.post("/api/auth/token", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok, branch_id=None):
    h = {"Authorization": f"Bearer {tok}"}
    if branch_id is not None:
        h["X-Branch-Id"] = str(branch_id)
    return h


def test_admin_role_includes_sales_permission(db_session):
    _, _, _, admin, _, _ = _seed_admin_and_cashier(db_session)
    assert has_permission(admin, Perm.SALES)


def test_admin_can_create_sale_and_deduct_stock(client, db_session):
    t, main, _, _, _, p = _seed_admin_and_cashier(db_session)
    tok = _login(client, "adm_sale", "AdminPass1234")
    payload = {
        "items": [{"product_id": p.id, "quantity": 2, "unit_price": 5, "discount": 0}],
        "payments": [{"method": "cash", "amount": 10}],
        "collection_status": "collected",
        "client_sale_id": "admin-android-1",
    }
    r = client.post("/api/sales", headers=_auth(tok), json=payload)
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert get_branch_stock(db_session, main.id, p.id).quantity_on_hand == Decimal("8.0000")


def test_cashier_still_can_create_sale(client, db_session):
    _, main, _, _, cash, p = _seed_admin_and_cashier(db_session)
    tok = _login(client, "cash_sale", "CashPass1234")
    r = client.post(
        "/api/sales",
        headers=_auth(tok),
        json={
            "items": [{"product_id": p.id, "quantity": 1, "unit_price": 5, "discount": 0}],
            "payments": [{"method": "cash", "amount": 5}],
            "client_sale_id": "cash-still-1",
        },
    )
    assert r.status_code == 200, r.text


def test_unmapped_role_denied_sales(client, db_session):
    t, main, _, _, _, p = _seed_admin_and_cashier(db_session)
    reports_only = User(
        username="reports_only",
        password_hash=auth_mod.get_password_hash("ReportsPass1234"),
        role="reports_only",
        tenant_id=t.id,
        branch_id=main.id,
        is_active=True,
    )
    db_session.add(reports_only)
    db_session.commit()
    assert not has_permission(reports_only, Perm.SALES)
    tok = _login(client, "reports_only", "ReportsPass1234")
    r = client.post(
        "/api/sales",
        headers=_auth(tok),
        json={
            "items": [{"product_id": p.id, "quantity": 1, "unit_price": 5, "discount": 0}],
            "payments": [{"method": "cash", "amount": 5}],
        },
    )
    assert r.status_code == 403
    assert "sales" in r.json()["detail"]


def test_admin_duplicate_client_sale_id_idempotent(client, db_session):
    _, main, _, _, _, p = _seed_admin_and_cashier(db_session)
    tok = _login(client, "adm_sale", "AdminPass1234")
    payload = {
        "items": [{"product_id": p.id, "quantity": 2, "unit_price": 5, "discount": 0}],
        "payments": [{"method": "cash", "amount": 10}],
        "client_sale_id": "admin-dup-1",
    }
    r1 = client.post("/api/sales", headers=_auth(tok, main.id), json=payload)
    r2 = client.post("/api/sales", headers=_auth(tok, main.id), json=payload)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    db_session.expire_all()
    assert get_branch_stock(db_session, main.id, p.id).quantity_on_hand == Decimal("8.0000")
    assert db_session.query(Sale).filter(Sale.client_sale_id == "admin-dup-1").count() == 1


def test_admin_cannot_cross_tenant_product(client, db_session):
    t1, main1, _, _, _, p1 = _seed_admin_and_cashier(db_session)
    t2 = Tenant(tenant_uid=str(uuid.uuid4()), name="Other")
    db_session.add(t2)
    db_session.flush()
    main2 = Branch(tenant_id=t2.id, name="Main2", code="M2", is_default=True, is_active=True)
    db_session.add(main2)
    db_session.flush()
    admin2 = User(
        username="adm_other",
        password_hash=auth_mod.get_password_hash("AdminPass1234"),
        role="admin",
        tenant_id=t2.id,
        branch_id=main2.id,
        is_active=True,
    )
    db_session.add(admin2)
    db_session.commit()
    tok = _login(client, "adm_other", "AdminPass1234")
    r = client.post(
        "/api/sales",
        headers=_auth(tok),
        json={
            "items": [{"product_id": p1.id, "quantity": 1, "unit_price": 5, "discount": 0}],
            "payments": [{"method": "cash", "amount": 5}],
            "client_sale_id": "cross-tenant",
        },
    )
    assert r.status_code in (400, 404, 403)
    db_session.expire_all()
    assert get_branch_stock(db_session, main1.id, p1.id).quantity_on_hand == Decimal("10.0000")