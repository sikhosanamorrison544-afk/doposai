"""Barcode auto-assign, restock API, and admin POS access gates."""
from __future__ import annotations

import os
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
from app.landing import post_login_path
from app.main import app
from app.models import InventoryMovement, Product, User
from app.permissions import Perm, can_access_pos, has_permission, user_permissions


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
        username="bar_admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
    )
    cashier = User(
        username="bar_cashier",
        password_hash=_hash("CashPass1234"),
        role="cashier",
        is_active=True,
    )
    db.add_all([admin, cashier])
    db.commit()
    db.refresh(admin)
    db.refresh(cashier)
    return admin, cashier


def _login(client, username, password):
    r = client.post("/api/auth/token", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_admin_does_not_get_sales_permission():
    admin = User(username="a", role="admin", password_hash="x", is_active=True)
    assert not has_permission(admin, Perm.SALES)
    assert not can_access_pos(admin)
    assert Perm.MANAGE_INVENTORY in user_permissions(admin)
    assert post_login_path(admin) == "/overview"


def test_cashier_keeps_sales_and_pos_landing():
    cashier = User(username="c", role="cashier", password_hash="x", is_active=True)
    assert has_permission(cashier, Perm.SALES)
    assert can_access_pos(cashier)
    assert post_login_path(cashier) == "/"


def test_create_product_auto_barcode_rejects_manual(client, db_session):
    _seed(db_session)
    tok = _login(client, "bar_admin", "AdminPass1234")["access_token"]
    bad = client.post(
        "/api/products",
        headers=_auth(tok),
        json={
            "name": "Manual Bar",
            "barcode": "CUSTOM-123",
            "stock_qty": 0,
            "cost_price": "1.00",
            "selling_price": "2.00",
            "is_active": True,
        },
    )
    assert bad.status_code == 400
    assert "Manual barcodes" in bad.json()["detail"]

    ok = client.post(
        "/api/products",
        headers=_auth(tok),
        json={
            "name": "Auto Bar",
            "barcode": None,
            "stock_qty": 5,
            "cost_price": "1.00",
            "selling_price": "2.00",
            "is_active": True,
        },
    )
    assert ok.status_code == 200, ok.text
    data = ok.json()
    assert data["barcode"].startswith("AUTO-")
    assert data["stock_qty"] == 5


def test_edit_preserves_barcode_and_ignores_stock_replace(client, db_session):
    _seed(db_session)
    tok = _login(client, "bar_admin", "AdminPass1234")["access_token"]
    created = client.post(
        "/api/products",
        headers=_auth(tok),
        json={
            "name": "Keep Code",
            "stock_qty": 20,
            "cost_price": "1.00",
            "selling_price": "3.00",
            "is_active": True,
        },
    ).json()
    code = created["barcode"]
    pid = created["id"]

    updated = client.put(
        f"/api/products/{pid}",
        headers=_auth(tok),
        json={
            "name": "Keep Code Renamed",
            "barcode": code,
            "stock_qty": 999,
            "cost_price": "1.50",
            "selling_price": "3.50",
            "is_active": True,
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["barcode"] == code
    assert body["name"] == "Keep Code Renamed"
    assert body["stock_qty"] == 20  # not replaced by 999

    change = client.put(
        f"/api/products/{pid}",
        headers=_auth(tok),
        json={
            "name": "Keep Code Renamed",
            "barcode": "HACKED-1",
            "stock_qty": 20,
            "cost_price": "1.50",
            "selling_price": "3.50",
            "is_active": True,
        },
    )
    assert change.status_code == 400


def test_restock_increments_and_audits(client, db_session):
    _seed(db_session)
    tok = _login(client, "bar_admin", "AdminPass1234")["access_token"]
    created = client.post(
        "/api/products",
        headers=_auth(tok),
        json={
            "name": "Restock Me",
            "stock_qty": 20,
            "cost_price": "1.00",
            "selling_price": "2.00",
            "is_active": True,
        },
    ).json()
    pid = created["id"]
    code = created["barcode"]

    zero = client.post(
        f"/api/products/{pid}/restock",
        headers=_auth(tok),
        json={"quantity_added": 0},
    )
    assert zero.status_code == 422

    neg = client.post(
        f"/api/products/{pid}/restock",
        headers=_auth(tok),
        json={"quantity_added": -3},
    )
    assert neg.status_code == 422

    ok = client.post(
        f"/api/products/{pid}/restock",
        headers=_auth(tok),
        json={"quantity_added": 8, "reason": "stock_received", "notes": "Shipment A"},
    )
    assert ok.status_code == 200, ok.text
    data = ok.json()
    assert data["previous_qty"] == 20
    assert data["quantity_added"] == 8
    assert data["resulting_qty"] == 28
    assert data["barcode"] == code
    assert data.get("movement_id") is not None

    product = db_session.query(Product).filter_by(id=pid).one()
    assert float(product.stock_qty) == 28
    moves = (
        db_session.query(InventoryMovement)
        .filter_by(product_id=pid)
        .order_by(InventoryMovement.id)
        .all()
    )
    assert any(abs(float(m.change_qty) - 8) < 0.01 for m in moves)
    assert any(m.id == data["movement_id"] for m in moves)


def test_concurrent_restock_sessions_preserve_both_receipts():
    """
    Two separate DB sessions restock the same product concurrently.
    Initial 20 + 8 + 5 must become 33 (no lost update).
    """
    import tempfile
    import threading
    from pathlib import Path

    from app.enterprise.inventory_ops import apply_product_stock_change

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name
    try:
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
            future=True,
        )

        def _enable_wal(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        from sqlalchemy import event

        event.listen(engine, "connect", _enable_wal)
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(
            bind=engine, autoflush=False, autocommit=False, future=True
        )

        with SessionLocal() as setup:
            product = Product(
                name="Concurrent Restock",
                barcode="AUTO-CONCUR-01",
                stock_qty=20,
                cost_price=Decimal("1"),
                selling_price=Decimal("2"),
                is_active=True,
            )
            setup.add(product)
            setup.commit()
            setup.refresh(product)
            product_id = product.id

        errors: list = []
        barrier = threading.Barrier(2)

        def _receipt(amount: float):
            try:
                session = SessionLocal()
                try:
                    barrier.wait(timeout=5)
                    apply_product_stock_change(
                        session,
                        product_id,
                        amount,
                        f"stock_received concurrent +{amount}",
                    )
                    session.commit()
                except Exception as e:
                    session.rollback()
                    errors.append(e)
                finally:
                    session.close()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=_receipt, args=(8.0,))
        t2 = threading.Thread(target=_receipt, args=(5.0,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"Concurrent restock failed: {errors}"
        with SessionLocal() as verify:
            final = verify.query(Product).filter_by(id=product_id).one()
            assert float(final.stock_qty) == 33.0
            moves = (
                verify.query(InventoryMovement)
                .filter_by(product_id=product_id)
                .all()
            )
            assert len(moves) == 2
            assert sorted(float(m.change_qty) for m in moves) == [5.0, 8.0]
    finally:
        Path(db_path).unlink(missing_ok=True)
        try:
            engine.dispose()
        except Exception:
            pass


def test_admin_cannot_create_sale(client, db_session):
    admin, cashier = _seed(db_session)
    product = Product(
        name="Sale Item",
        barcode="AUTO-000099",
        stock_qty=10,
        cost_price=Decimal("1"),
        selling_price=Decimal("5"),
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    admin_tok = _login(client, "bar_admin", "AdminPass1234")["access_token"]
    denied = client.post(
        "/api/sales",
        headers=_auth(admin_tok),
        json={
            "items": [
                {
                    "product_id": product.id,
                    "quantity": 1,
                    "unit_price": 5,
                    "discount": 0,
                }
            ],
            "payments": [{"method": "cash", "amount": 5}],
            "collection_status": "collected",
        },
    )
    assert denied.status_code == 403

    cash_tok = _login(client, "bar_cashier", "CashPass1234")["access_token"]
    # Cashier may sell (payload shape may still fail validation — only assert not 403)
    allowed = client.post(
        "/api/sales",
        headers=_auth(cash_tok),
        json={
            "items": [
                {
                    "product_id": product.id,
                    "quantity": 1,
                    "unit_price": 5,
                    "discount": 0,
                }
            ],
            "payments": [{"method": "cash", "amount": 5}],
            "collection_status": "collected",
        },
    )
    assert allowed.status_code != 403


def test_overview_has_management_and_fab(client, db_session):
    _seed(db_session)
    _login(client, "bar_admin", "AdminPass1234")
    html = client.get("/overview").text
    assert "Management" in html
    assert 'href="/billing"' in html
    assert 'href="/pending-collection"' in html
    assert 'href="/refunds"' in html
    assert 'href="/layby"' in html
    assert 'id="ov-fab-toggle"' in html
    assert 'id="ov-fab-notifications"' in html
    assert 'id="ov-fab-settings"' in html
    assert 'id="ov-fab-theme"' in html
    assert "overview.css?v=11" in html
    assert 'id="ov-open-pos"' in html
    assert "hidden" in html  # Open POS starts hidden until sales perm
    assert html.count('href="/admin"') == 1


def test_login_token_includes_pos_flags(client, db_session):
    _seed(db_session)
    admin = _login(client, "bar_admin", "AdminPass1234")
    assert admin["landing_path"] == "/overview"
    assert admin["can_access_pos"] is False
    assert "sales" not in admin["permissions"]

    cash = _login(client, "bar_cashier", "CashPass1234")
    assert cash["landing_path"] == "/"
    assert cash["can_access_pos"] is True
    assert "sales" in cash["permissions"]
