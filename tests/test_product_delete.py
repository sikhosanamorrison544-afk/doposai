"""Product deletion password + authorization regression tests."""
from __future__ import annotations

import os
import uuid

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
from app.enterprise_models import Branch, BranchProductStock
from app.inventory_service import seed_main_branch_from_legacy, sync_legacy_product_stock
from app.main import app as fastapi_app
from app.models import Product, User
from app.quotation_models import Tenant

import app.enterprise_models  # noqa: F401
import app.branch_models  # noqa: F401
import app.accounting_models  # noqa: F401


ADMIN_PASSWORD = "AdminPass1234"


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
    with TestClient(fastapi_app, raise_server_exceptions=False) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


def _hash(pw=ADMIN_PASSWORD):
    return auth_mod.get_password_hash(pw)


def _seed(db_session):
    t = Tenant(tenant_uid=str(uuid.uuid4()), name="Delete Shop")
    db_session.add(t)
    db_session.flush()
    admin = User(
        username="del_admin",
        password_hash=_hash(),
        role="admin",
        tenant_id=t.id,
        is_active=True,
    )
    cashier = User(
        username="del_cashier",
        password_hash=_hash("CashPass1234"),
        role="cashier",
        tenant_id=t.id,
        is_active=True,
    )
    db_session.add_all([admin, cashier])
    db_session.flush()
    main = Branch(
        tenant_id=t.id,
        name="Main Branch",
        code="MAIN",
        is_default=True,
        is_active=True,
    )
    db_session.add(main)
    db_session.flush()
    p = Product(
        name="Tape Measure",
        barcode="DEL-TAPE-1",
        selling_price=10,
        cost_price=4,
        stock_qty=3,
        tenant_id=t.id,
        is_active=True,
    )
    db_session.add(p)
    db_session.flush()
    seed_main_branch_from_legacy(db_session, tenant_id=t.id, branch_id=main.id, product=p)
    sync_legacy_product_stock(db_session, p.id)
    db_session.commit()
    return t, admin, cashier, main, p


def _login(client, username, password=ADMIN_PASSWORD):
    r = client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _delete(client, tok, product_id, password):
    return client.request(
        "DELETE",
        f"/api/products/{product_id}",
        headers=_auth(tok),
        json={"admin_password": password},
    )


def test_empty_password_rejected(client, db_session):
    t, admin, cashier, main, p = _seed(db_session)
    tok = _login(client, "del_admin")
    r = _delete(client, tok, p.id, "")
    assert r.status_code in (400, 422)
    db_session.refresh(p)
    assert db_session.query(Product).filter_by(id=p.id).one().is_active is True


def test_incorrect_password_rejected_product_intact(client, db_session):
    t, admin, cashier, main, p = _seed(db_session)
    tok = _login(client, "del_admin")
    r = _delete(client, tok, p.id, "WrongPassword999")
    assert r.status_code == 403
    assert "password" in r.json()["detail"].lower()
    assert db_session.query(Product).filter_by(id=p.id).one() is not None
    assert float(db_session.query(Product).filter_by(id=p.id).one().stock_qty) == 3.0


def test_product_name_as_password_rejected(client, db_session):
    """Regression: typing the product name into the password field must not delete."""
    t, admin, cashier, main, p = _seed(db_session)
    tok = _login(client, "del_admin")
    r = _delete(client, tok, p.id, "Tape Measure")
    assert r.status_code == 403
    assert db_session.query(Product).filter_by(id=p.id).one().is_active is True


def test_correct_admin_password_deletes_product(client, db_session):
    t, admin, cashier, main, p = _seed(db_session)
    tok = _login(client, "del_admin")
    pid = p.id
    r = _delete(client, tok, pid, ADMIN_PASSWORD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("deleted") is True
    assert db_session.query(Product).filter_by(id=pid).one_or_none() is None
    assert (
        db_session.query(BranchProductStock).filter_by(product_id=pid).one_or_none()
        is None
    )


def test_cashier_cannot_delete_product(client, db_session):
    t, admin, cashier, main, p = _seed(db_session)
    tok = _login(client, "del_cashier", "CashPass1234")
    r = _delete(client, tok, p.id, "CashPass1234")
    assert r.status_code in (401, 403)
    assert db_session.query(Product).filter_by(id=p.id).one().is_active is True


def test_unauthenticated_cannot_delete(client, db_session):
    t, admin, cashier, main, p = _seed(db_session)
    r = client.request(
        "DELETE",
        f"/api/products/{p.id}",
        json={"admin_password": ADMIN_PASSWORD},
    )
    assert r.status_code in (401, 403)
    assert db_session.query(Product).filter_by(id=p.id).one() is not None


def test_missing_password_field_rejected(client, db_session):
    t, admin, cashier, main, p = _seed(db_session)
    tok = _login(client, "del_admin")
    r = client.request(
        "DELETE",
        f"/api/products/{p.id}",
        headers=_auth(tok),
        json={},
    )
    assert r.status_code == 422
    assert db_session.query(Product).filter_by(id=p.id).one() is not None


def test_duplicate_delete_after_success_is_not_found(client, db_session):
    """Second DELETE after success cannot repeat a destructive action on the same row."""
    t, admin, cashier, main, p = _seed(db_session)
    tok = _login(client, "del_admin")
    pid = p.id
    first = _delete(client, tok, pid, ADMIN_PASSWORD)
    assert first.status_code == 200
    second = _delete(client, tok, pid, ADMIN_PASSWORD)
    assert second.status_code in (404, 400, 403)
