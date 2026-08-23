"""
Product creation branch regression tests (Section 14 + Section 15 gate).

Covers atomic product creation:
  - Main Branch create
  - secondary branch create
  - opening stock only on selected branch
  - other branches stay zero
  - Product.stock_qty shadow equals total branch stock
  - consolidated scope=all rejected
  - unauthorized / inactive / cross-tenant branch rejected
  - missing schema → 503 (not 500)
  - duplicate barcode → 409
  - Decimal opening stock exact
  - inventory-row failure rolls back Product creation
  - retry after failure creates no duplicates
  - single-branch compat still works
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth as auth_mod
from app.database import Base, get_db
from app.enterprise_models import Branch, BranchProductStock
from app.branch_models import UserBranch
from app.inventory_service import (
    MOVEMENT_OPENING_STOCK,
    create_product_with_opening_stock,
    get_branch_stock,
    to_qty,
    total_branch_stock_for_product,
)
from app.main import app as fastapi_app
from app.models import InventoryMovement, Product, User
from app.quotation_models import Tenant

import app.enterprise_models  # noqa: F401
import app.branch_models  # noqa: F401
import app.accounting_models  # noqa: F401


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


def _tenant(db, name="Prod Create Co"):
    t = Tenant(tenant_uid=str(uuid.uuid4()), name=name)
    db.add(t)
    db.flush()
    return t


def _user(db, tenant_id, username, role="admin", **kw):
    u = User(
        username=username,
        password_hash=_hash(),
        role=role,
        tenant_id=tenant_id,
        is_active=True,
        **kw,
    )
    db.add(u)
    db.flush()
    return u


def _branch(db, tenant_id, name, code, is_default=False, is_active=True):
    b = Branch(
        tenant_id=tenant_id,
        name=name,
        code=code,
        is_default=is_default,
        is_active=is_active,
    )
    db.add(b)
    db.flush()
    return b


def _login(client, username):
    r = client.post(
        "/api/auth/token",
        data={"username": username, "password": "AdminPass1234"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok, branch_id=None):
    h = {"Authorization": f"Bearer {tok}"}
    if branch_id is not None:
        h["X-Branch-Id"] = str(branch_id)
    return h


def _create_payload(**kw):
    payload = {
        "name": "Widget",
        "barcode": None,
        "category_id": None,
        "stock_qty": 5,
        "cost_price": 3,
        "selling_price": 10,
        "is_active": True,
        "expiry_date": None,
    }
    payload.update(kw)
    return payload


# ---------------------------------------------------------------------------
# 1. Product creation in Main Branch
# ---------------------------------------------------------------------------
def test_create_product_main_branch(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own_main")
    main = _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    db_session.commit()

    tok = _login(client, "own_main")
    r = client.post("/api/products", headers=_auth(tok), json=_create_payload(stock_qty=5))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"]

    product = db_session.query(Product).filter(Product.id == body["id"]).one()
    snap = get_branch_stock(db_session, main.id, product.id)
    assert snap.quantity_on_hand == Decimal("5.0000")


# ---------------------------------------------------------------------------
# 2. Product creation in a secondary branch
# ---------------------------------------------------------------------------
def test_create_product_secondary_branch(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own_sec")
    main = _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    west = _branch(db_session, t.id, "West", "WEST")
    db_session.commit()

    tok = _login(client, "own_sec")
    r = client.post(
        "/api/products",
        headers=_auth(tok, west.id),
        json=_create_payload(stock_qty=7, branch_id=west.id),
    )
    assert r.status_code == 200, r.text
    product = db_session.query(Product).filter(Product.id == r.json()["id"]).one()
    assert get_branch_stock(db_session, west.id, product.id).quantity_on_hand == Decimal("7.0000")


# ---------------------------------------------------------------------------
# 3. Opening stock applies only to selected branch
# ---------------------------------------------------------------------------
def test_opening_stock_only_selected_branch(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own_sel")
    main = _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    west = _branch(db_session, t.id, "West", "WEST")
    db_session.commit()

    tok = _login(client, "own_sel")
    r = client.post(
        "/api/products",
        headers=_auth(tok, west.id),
        json=_create_payload(stock_qty=9, branch_id=west.id),
    )
    assert r.status_code == 200, r.text
    product = db_session.query(Product).filter(Product.id == r.json()["id"]).one()
    assert get_branch_stock(db_session, west.id, product.id).quantity_on_hand == Decimal("9.0000")

    movement = (
        db_session.query(InventoryMovement)
        .filter(InventoryMovement.product_id == product.id)
        .one()
    )
    assert movement.movement_type == MOVEMENT_OPENING_STOCK
    assert to_qty(movement.change_qty) == Decimal("9.0000")


# ---------------------------------------------------------------------------
# 4. Other branches remain zero
# ---------------------------------------------------------------------------
def test_other_branches_remain_zero(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own_zero")
    main = _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    west = _branch(db_session, t.id, "West", "WEST")
    east = _branch(db_session, t.id, "East", "EAST")
    db_session.commit()

    tok = _login(client, "own_zero")
    r = client.post(
        "/api/products",
        headers=_auth(tok, west.id),
        json=_create_payload(stock_qty=11, branch_id=west.id),
    )
    assert r.status_code == 200, r.text
    product = db_session.query(Product).filter(Product.id == r.json()["id"]).one()
    assert get_branch_stock(db_session, west.id, product.id).quantity_on_hand == Decimal("11.0000")
    assert get_branch_stock(db_session, main.id, product.id).quantity_on_hand == Decimal("0.0000")
    assert get_branch_stock(db_session, east.id, product.id).quantity_on_hand == Decimal("0.0000")


# ---------------------------------------------------------------------------
# 5. Product shadow equals total branch stock
# ---------------------------------------------------------------------------
def test_product_shadow_equals_total_branch_stock(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own_shadow")
    main = _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    west = _branch(db_session, t.id, "West", "WEST")
    db_session.commit()

    tok = _login(client, "own_shadow")
    r = client.post(
        "/api/products",
        headers=_auth(tok, west.id),
        json=_create_payload(stock_qty=13, branch_id=west.id),
    )
    assert r.status_code == 200, r.text
    product = db_session.query(Product).filter(Product.id == r.json()["id"]).one()
    db_session.refresh(product)
    total = total_branch_stock_for_product(db_session, product.id)
    assert total == Decimal("13.0000")
    assert float(product.stock_qty) == float(total)


# ---------------------------------------------------------------------------
# 6. Consolidated scope=all rejected
# ---------------------------------------------------------------------------
def test_consolidated_scope_rejected(client, db_session):
    t = _tenant(db_session)
    admin = _user(db_session, t.id, "own_all")
    _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    db_session.commit()

    tok = _login(client, "own_all")
    sw = client.post("/api/branches/switch", headers=_auth(tok), json={"scope": "all"})
    assert sw.status_code == 200, sw.text
    all_tok = sw.json()["access_token"]

    r = client.post("/api/products", headers=_auth(all_tok), json=_create_payload(stock_qty=1))
    assert r.status_code == 400
    assert "specific branch" in r.json()["detail"].lower()
    assert db_session.query(Product).count() == 0


# ---------------------------------------------------------------------------
# 7. Unauthorized branch rejected
# ---------------------------------------------------------------------------
def test_unauthorized_branch_rejected(db_session):
    from fastapi import HTTPException

    t = _tenant(db_session)
    main = _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    west = _branch(db_session, t.id, "West", "WEST")
    cash = _user(db_session, t.id, "cash_unauth", role="cashier", branch_id=main.id)
    db_session.add(
        UserBranch(
            tenant_id=t.id,
            user_id=cash.id,
            branch_id=main.id,
            is_default=True,
            is_active=True,
            role="cashier",
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as ei:
        create_product_with_opening_stock(
            db_session,
            user=cash,
            name="No Access",
            category_id=None,
            stock_qty=1,
            reserved_qty=0,
            cost_price=1,
            selling_price=2,
            explicit_branch_id=west.id,
        )
    assert ei.value.status_code == 403


# ---------------------------------------------------------------------------
# 8. Inactive branch rejected
# ---------------------------------------------------------------------------
def test_inactive_branch_rejected(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own_inactive")
    _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    dead = _branch(db_session, t.id, "Dead", "DEAD", is_active=False)
    db_session.commit()

    tok = _login(client, "own_inactive")
    r = client.post(
        "/api/products",
        headers=_auth(tok, dead.id),
        json=_create_payload(stock_qty=1, branch_id=dead.id),
    )
    assert r.status_code == 400
    assert "inactive" in r.json()["detail"].lower()
    assert db_session.query(Product).count() == 0


# ---------------------------------------------------------------------------
# 9. Cross-tenant branch rejected
# ---------------------------------------------------------------------------
def test_cross_tenant_branch_rejected(client, db_session):
    t = _tenant(db_session, "Tenant A")
    t2 = _tenant(db_session, "Tenant B")
    _user(db_session, t.id, "own_a")
    _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    other_main = _branch(db_session, t2.id, "Other Main", "MAIN", is_default=True)
    db_session.commit()

    tok = _login(client, "own_a")
    r = client.post(
        "/api/products",
        headers=_auth(tok, other_main.id),
        json=_create_payload(stock_qty=1, branch_id=other_main.id),
    )
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()
    assert db_session.query(Product).count() == 0


# ---------------------------------------------------------------------------
# 10. Missing schema returns controlled 503, not 500
# ---------------------------------------------------------------------------
def test_missing_schema_returns_503(db_session, monkeypatch):
    t = _tenant(db_session)
    admin = _user(db_session, t.id, "own_missing")
    _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    db_session.commit()

    # Drop a required column to simulate a pre-migration database, after the
    # fixtures exist. (branches.email is a plain column with no index/FK.)
    db_session.execute(text("ALTER TABLE branches DROP COLUMN email"))
    db_session.commit()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        create_product_with_opening_stock(
            db_session,
            user=admin,
            name="Will Fail",
            category_id=None,
            stock_qty=1,
            reserved_qty=0,
            cost_price=1,
            selling_price=2,
        )
    assert ei.value.status_code == 503
    assert "branch schema" in ei.value.detail.lower()
    assert db_session.query(Product).count() == 0


# ---------------------------------------------------------------------------
# 11. Duplicate barcode returns 409
# ---------------------------------------------------------------------------
def test_duplicate_barcode_conflict(db_session, monkeypatch):
    t = _tenant(db_session)
    admin = _user(db_session, t.id, "own_dup")
    _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    existing = Product(
        name="Existing",
        barcode="AUTO-000001",
        selling_price=10,
        cost_price=4,
        stock_qty=0,
        tenant_id=t.id,
    )
    db_session.add(existing)
    db_session.commit()

    # Always return the taken barcode → barcode collisions exhaust retries.
    monkeypatch.setattr(
        "app.product_barcodes.generate_unique_barcode", lambda db, user: "AUTO-000001"
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        create_product_with_opening_stock(
            db_session,
            user=admin,
            name="Duplicate",
            category_id=None,
            stock_qty=1,
            reserved_qty=0,
            cost_price=1,
            selling_price=2,
        )
    assert ei.value.status_code == 409
    assert db_session.query(Product).count() == 1  # only the pre-existing row


# ---------------------------------------------------------------------------
# 12. Decimal opening stock remains exact
# ---------------------------------------------------------------------------
def test_decimal_opening_stock_exact(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own_dec")
    main = _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    db_session.commit()

    tok = _login(client, "own_dec")
    r = client.post(
        "/api/products",
        headers=_auth(tok, main.id),
        json=_create_payload(stock_qty=0.1, branch_id=main.id),
    )
    assert r.status_code == 200, r.text
    product = db_session.query(Product).filter(Product.id == r.json()["id"]).one()
    assert get_branch_stock(db_session, main.id, product.id).quantity_on_hand == Decimal("0.1000")


# ---------------------------------------------------------------------------
# 13. Inventory-row failure rolls back Product creation
# ---------------------------------------------------------------------------
def test_inventory_failure_rolls_back_product(db_session, monkeypatch):
    t = _tenant(db_session)
    admin = _user(db_session, t.id, "own_rollback")
    _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    db_session.commit()

    def boom(db, **kwargs):
        raise RuntimeError("inventory movement failure")

    monkeypatch.setattr("app.inventory_service.increase_branch_stock", boom)

    with pytest.raises(RuntimeError):
        create_product_with_opening_stock(
            db_session,
            user=admin,
            name="Rollback Me",
            category_id=None,
            stock_qty=5,
            reserved_qty=0,
            cost_price=1,
            selling_price=2,
        )
    assert db_session.query(Product).count() == 0
    assert db_session.query(BranchProductStock).count() == 0


# ---------------------------------------------------------------------------
# 14. Retry after failure creates no duplicates
# ---------------------------------------------------------------------------
def test_retry_after_failure_no_duplicates(db_session, monkeypatch):
    t = _tenant(db_session)
    admin = _user(db_session, t.id, "own_retry")
    main = _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    existing = Product(
        name="Existing",
        barcode="AUTO-000001",
        selling_price=10,
        cost_price=4,
        stock_qty=0,
        tenant_id=t.id,
    )
    db_session.add(existing)
    db_session.commit()

    calls = {"n": 0}

    def fake_barcode(db, user):
        calls["n"] += 1
        return "AUTO-000001" if calls["n"] == 1 else "AUTO-000002"

    monkeypatch.setattr("app.product_barcodes.generate_unique_barcode", fake_barcode)

    product = create_product_with_opening_stock(
        db_session,
        user=admin,
        name="Retry Product",
        category_id=None,
        stock_qty=2,
        reserved_qty=0,
        cost_price=1,
        selling_price=2,
    )
    assert product.barcode == "AUTO-000002"
    assert db_session.query(Product).count() == 2  # existing + new
    assert (
        db_session.query(Product).filter(Product.name == "Retry Product").count() == 1
    )
    assert get_branch_stock(db_session, main.id, product.id).quantity_on_hand == Decimal("2.0000")


# ---------------------------------------------------------------------------
# 15. Existing single-branch product creation still works
# ---------------------------------------------------------------------------
def test_single_branch_product_creation_still_works(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own_solo")
    db_session.commit()  # no Branch rows yet — auto Main Branch must be created

    tok = _login(client, "own_solo")
    r = client.post("/api/products", headers=_auth(tok), json=_create_payload(stock_qty=3))
    assert r.status_code == 200, r.text
    body = r.json()
    product = db_session.query(Product).filter(Product.id == body["id"]).one()

    branch = db_session.query(Branch).filter(Branch.tenant_id == t.id).one()
    assert branch.is_default is True
    assert get_branch_stock(db_session, branch.id, product.id).quantity_on_hand == Decimal("3.0000")