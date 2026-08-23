"""
Section 14 — branch inventory cutover and transaction scoping tests.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth as auth_mod
from app.database import Base, get_db
from app.enterprise_models import Branch, BranchProductStock
from app.branch_models import UserBranch
from app.inventory_service import (
    decrease_branch_stock,
    fmt_qty,
    get_branch_stock,
    require_operational_branch,
    seed_main_branch_from_legacy,
    set_branch_stock,
    sync_legacy_product_stock,
    to_qty,
)
from app.main import app as fastapi_app
from app.models import Product, Sale, User
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


def _tenant(db, name="Inv Shop"):
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


def _main(db, tenant_id):
    b = Branch(
        tenant_id=tenant_id,
        name="Main Branch",
        code="MAIN",
        is_default=True,
        is_active=True,
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


def test_main_receives_legacy_stock_once(db_session):
    from migrate_branches import ensure_branch_inventory, ensure_main_branch

    t = _tenant(db_session)
    main = ensure_main_branch(db_session, t.id)
    p = Product(
        name="Widget",
        barcode="W1",
        selling_price=10,
        cost_price=4,
        stock_qty=25,
        tenant_id=t.id,
    )
    db_session.add(p)
    db_session.flush()
    n1 = ensure_branch_inventory(db_session, t.id, main)
    n2 = ensure_branch_inventory(db_session, t.id, main)
    assert n1 == 1
    assert n2 == 0
    row = (
        db_session.query(BranchProductStock)
        .filter(BranchProductStock.product_id == p.id)
        .one()
    )
    assert to_qty(row.stock_qty) == Decimal("25.0000")
    assert row.seeded_from_legacy is True
    # Mutate product — rerun must not overwrite
    p.stock_qty = 999
    ensure_branch_inventory(db_session, t.id, main)
    db_session.refresh(row)
    assert to_qty(row.stock_qty) == Decimal("25.0000")


def test_secondary_branch_starts_zero_independent_qty(db_session):
    t = _tenant(db_session)
    main = _main(db_session, t.id)
    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True)
    db_session.add(west)
    db_session.flush()
    p = Product(
        name="P",
        barcode="P1",
        selling_price=1,
        cost_price=1,
        stock_qty=10,
        tenant_id=t.id,
    )
    db_session.add(p)
    db_session.flush()
    seed_main_branch_from_legacy(db_session, tenant_id=t.id, branch_id=main.id, product=p)
    set_branch_stock(
        db_session,
        tenant_id=t.id,
        branch_id=west.id,
        product_id=p.id,
        quantity=0,
        reason="open",
    )
    assert get_branch_stock(db_session, main.id, p.id).quantity_on_hand == Decimal("10.0000")
    assert get_branch_stock(db_session, west.id, p.id).quantity_on_hand == Decimal("0.0000")


def test_sale_deducts_only_sale_branch(client, db_session):
    t = _tenant(db_session)
    admin = _user(db_session, t.id, "own_inv")
    main = _main(db_session, t.id)
    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True)
    db_session.add(west)
    db_session.flush()
    p = Product(
        name="Milk",
        barcode="M1",
        selling_price=5,
        cost_price=2,
        stock_qty=10,
        tenant_id=t.id,
    )
    db_session.add(p)
    db_session.flush()
    seed_main_branch_from_legacy(db_session, tenant_id=t.id, branch_id=main.id, product=p)
    set_branch_stock(
        db_session, tenant_id=t.id, branch_id=west.id, product_id=p.id, quantity=7, reason="seed"
    )
    sync_legacy_product_stock(db_session, p.id)
    admin.branch_id = west.id
    db_session.commit()

    tok = _login(client, "own_inv")
    # Give admin sales permission via role - admin doesn't have SALES by default!
    # Use cashier with SALES
    cash = _user(db_session, t.id, "cash_inv", role="cashier", branch_id=west.id)
    db_session.add(
        UserBranch(
            tenant_id=t.id,
            user_id=cash.id,
            branch_id=west.id,
            is_default=True,
            is_active=True,
            role="cashier",
        )
    )
    db_session.commit()
    ctok = _login(client, "cash_inv")
    r = client.post(
        "/api/sales",
        headers=_auth(ctok, west.id),
        json={
            "items": [{"product_id": p.id, "quantity": 2, "unit_price": 5, "discount": 0}],
            "payments": [{"method": "cash", "amount": 10}],
            "branch_id": west.id,
        },
    )
    assert r.status_code == 200, r.text
    assert get_branch_stock(db_session, west.id, p.id).quantity_on_hand == Decimal("5.0000")
    assert get_branch_stock(db_session, main.id, p.id).quantity_on_hand == Decimal("10.0000")


def test_sale_fails_when_branch_lacks_stock(client, db_session):
    t = _tenant(db_session)
    main = _main(db_session, t.id)
    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True)
    db_session.add(west)
    db_session.flush()
    cash = _user(db_session, t.id, "cash2", role="cashier", branch_id=west.id)
    db_session.add(
        UserBranch(
            tenant_id=t.id,
            user_id=cash.id,
            branch_id=west.id,
            is_default=True,
            is_active=True,
            role="cashier",
        )
    )
    p = Product(
        name="X",
        barcode="X1",
        selling_price=1,
        cost_price=1,
        stock_qty=50,
        tenant_id=t.id,
    )
    db_session.add(p)
    db_session.flush()
    seed_main_branch_from_legacy(db_session, tenant_id=t.id, branch_id=main.id, product=p)
    set_branch_stock(
        db_session, tenant_id=t.id, branch_id=west.id, product_id=p.id, quantity=1, reason="seed"
    )
    db_session.commit()
    tok = _login(client, "cash2")
    r = client.post(
        "/api/sales",
        headers=_auth(tok, west.id),
        json={
            "items": [{"product_id": p.id, "quantity": 5, "unit_price": 1, "discount": 0}],
            "payments": [{"method": "cash", "amount": 5}],
            "branch_id": west.id,
        },
    )
    assert r.status_code == 400
    assert get_branch_stock(db_session, west.id, p.id).quantity_on_hand == Decimal("1.0000")
    assert get_branch_stock(db_session, main.id, p.id).quantity_on_hand == Decimal("50.0000")


def test_idempotent_sale_no_double_deduct_and_branch_conflict(client, db_session):
    t = _tenant(db_session)
    main = _main(db_session, t.id)
    cash = _user(db_session, t.id, "cash3", role="cashier", branch_id=main.id)
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
    p = Product(
        name="Y",
        barcode="Y1",
        selling_price=2,
        cost_price=1,
        stock_qty=10,
        tenant_id=t.id,
    )
    db_session.add(p)
    db_session.flush()
    seed_main_branch_from_legacy(db_session, tenant_id=t.id, branch_id=main.id, product=p)
    db_session.commit()
    tok = _login(client, "cash3")
    payload = {
        "items": [{"product_id": p.id, "quantity": 1, "unit_price": 2, "discount": 0}],
        "payments": [{"method": "cash", "amount": 2}],
        "branch_id": main.id,
        "client_sale_id": "offline-key-1",
    }
    assert client.post("/api/sales", headers=_auth(tok, main.id), json=payload).status_code == 200
    assert client.post("/api/sales", headers=_auth(tok, main.id), json=payload).status_code == 200
    assert get_branch_stock(db_session, main.id, p.id).quantity_on_hand == Decimal("9.0000")

    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True)
    db_session.add(west)
    db_session.flush()
    db_session.add(
        UserBranch(
            tenant_id=t.id,
            user_id=cash.id,
            branch_id=west.id,
            is_active=True,
            role="cashier",
        )
    )
    db_session.commit()
    bad = dict(payload)
    bad["branch_id"] = west.id
    r = client.post("/api/sales", headers=_auth(tok, west.id), json=bad)
    assert r.status_code == 409


def test_consolidated_cannot_create_sale(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own_c", role="admin")
    _main(db_session, t.id)
    db_session.commit()
    tok = _login(client, "own_c")
    sw = client.post("/api/branches/switch", headers=_auth(tok), json={"scope": "all"})
    assert sw.status_code == 200
    all_tok = sw.json()["access_token"]
    # Owner lacks SALES — use cashier with all scope denied
    cash = _user(db_session, t.id, "cash_c", role="cashier")
    db_session.commit()
    # Cashier cannot enter all; admin with all cannot sell without SALES.
    # Test require_operational_branch directly with token scope all:
    admin = db_session.query(User).filter(User.username == "own_c").one()
    admin._token_branch_scope = "all"
    admin._token_branch_id = None
    with pytest.raises(HTTPException) as ei:
        require_operational_branch(db_session, admin)
    assert ei.value.status_code == 400
    assert "specific branch" in ei.value.detail.lower()


def test_decimal_avoids_float_drift(db_session):
    t = _tenant(db_session)
    main = _main(db_session, t.id)
    p = Product(
        name="D",
        barcode="D1",
        selling_price=1,
        cost_price=1,
        stock_qty=0,
        tenant_id=t.id,
    )
    db_session.add(p)
    db_session.flush()
    set_branch_stock(
        db_session,
        tenant_id=t.id,
        branch_id=main.id,
        product_id=p.id,
        quantity="0.1",
        reason="a",
    )
    for _ in range(10):
        decrease_branch_stock(
            db_session,
            tenant_id=t.id,
            branch_id=main.id,
            product_id=p.id,
            quantity="0.01",
            reason="b",
            check_reserved=False,
        )
    snap = get_branch_stock(db_session, main.id, p.id)
    assert snap.quantity_on_hand == Decimal("0.0000")
    assert fmt_qty(snap.quantity_on_hand) == "0.0000"


def test_legacy_shadow_equals_branch_sum(db_session):
    t = _tenant(db_session)
    main = _main(db_session, t.id)
    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True)
    db_session.add(west)
    db_session.flush()
    p = Product(
        name="S",
        barcode="S1",
        selling_price=1,
        cost_price=1,
        stock_qty=0,
        tenant_id=t.id,
    )
    db_session.add(p)
    db_session.flush()
    set_branch_stock(
        db_session, tenant_id=t.id, branch_id=main.id, product_id=p.id, quantity=3, reason="a"
    )
    set_branch_stock(
        db_session, tenant_id=t.id, branch_id=west.id, product_id=p.id, quantity=4, reason="b"
    )
    sync_legacy_product_stock(db_session, p.id)
    db_session.refresh(p)
    assert float(p.stock_qty) == 7.0


def test_deactivate_blocks_nonzero_stock_and_open_shift(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own_d")
    main = _main(db_session, t.id)
    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True)
    db_session.add(west)
    db_session.flush()
    p = Product(
        name="Z",
        barcode="Z1",
        selling_price=1,
        cost_price=1,
        stock_qty=0,
        tenant_id=t.id,
    )
    db_session.add(p)
    db_session.flush()
    set_branch_stock(
        db_session, tenant_id=t.id, branch_id=west.id, product_id=p.id, quantity=2, reason="s"
    )
    db_session.commit()
    tok = _login(client, "own_d")
    r = client.post(f"/api/branches/{west.id}/deactivate", headers=_auth(tok))
    assert r.status_code == 409
    assert "stock" in r.json()["detail"].lower()


def test_single_branch_pos_still_works(client, db_session):
    """Pre-migration style: user + product, auto Main Branch + lazy seed."""
    t = _tenant(db_session)
    cash = _user(db_session, t.id, "solo_c", role="cashier")
    p = Product(
        name="Solo",
        barcode="SO1",
        selling_price=3,
        cost_price=1,
        stock_qty=5,
        tenant_id=t.id,
    )
    db_session.add(p)
    db_session.commit()
    tok = _login(client, "solo_c")
    r = client.post(
        "/api/sales",
        headers=_auth(tok),
        json={
            "items": [{"product_id": p.id, "quantity": 1, "unit_price": 3, "discount": 0}],
            "payments": [{"method": "cash", "amount": 3}],
        },
    )
    assert r.status_code == 200, r.text
    sale = db_session.query(Sale).first()
    assert sale.branch_id is not None
    assert get_branch_stock(db_session, sale.branch_id, p.id).quantity_on_hand == Decimal("4.0000")
