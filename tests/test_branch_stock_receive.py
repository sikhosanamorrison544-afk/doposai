"""
Branch stock receive/restock consistency tests.

Reproduces and guards the rule that BranchProductStock.stock_qty is the
authoritative source of truth for the active branch, and that the
``POST /api/products/{id}/restock`` path increments the branch row
(not only the legacy Product.stock_qty shadow).
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
from app.database import Base, get_db
from app.enterprise_models import Branch, BranchProductStock
from app.inventory_service import (
    get_branch_stock,
    seed_main_branch_from_legacy,
    set_branch_stock,
    sync_legacy_product_stock,
    to_qty,
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
    with TestClient(fastapi_app, raise_server_exceptions=False) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


def _hash(pw="AdminPass1234"):
    return auth_mod.get_password_hash(pw)


def _tenant(db, name="Receive Shop"):
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


def _branch(db, tenant_id, name, code, is_default=False):
    b = Branch(
        tenant_id=tenant_id,
        name=name,
        code=code,
        is_default=is_default,
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


def _seed_scenario(db_session):
    """Two branches, product at 5, main seeded from legacy, west at 0."""
    t = _tenant(db_session)
    admin = _user(db_session, t.id, "owner_rx", role="admin")
    main = _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    west = _branch(db_session, t.id, "West", "WEST")
    p = Product(
        name="Widget",
        barcode="W1",
        selling_price=10,
        cost_price=4,
        stock_qty=5,
        tenant_id=t.id,
    )
    db_session.add(p)
    db_session.flush()
    seed_main_branch_from_legacy(db_session, tenant_id=t.id, branch_id=main.id, product=p)
    set_branch_stock(
        db_session, tenant_id=t.id, branch_id=west.id, product_id=p.id, quantity=0, reason="open"
    )
    sync_legacy_product_stock(db_session, p.id)
    db_session.commit()
    return t, admin, main, west, p


def _bpg(db_session, branch_id, product_id):
    return (
        db_session.query(BranchProductStock)
        .filter(
            BranchProductStock.branch_id == branch_id,
            BranchProductStock.product_id == product_id,
        )
        .one()
    )


def _movements(db_session, product_id):
    return (
        db_session.query(InventoryMovement)
        .filter(InventoryMovement.product_id == product_id)
        .order_by(InventoryMovement.id.asc())
        .all()
    )


def _restock(client, tok, product_id, qty, branch_id=None, movement_id=None):
    payload = {"quantity_added": qty, "reason": "stock_received", "notes": None}
    if movement_id:
        payload["client_movement_id"] = movement_id
    return client.post(
        f"/api/products/{product_id}/restock",
        headers=_auth(tok, branch_id),
        json=payload,
    )


# --- 1..7: reproduce + branch-authoritative increment ---

def test_reproduce_restock_branch_inconsistency(client, db_session):
    """Document the exact data path: restock must touch BranchProductStock."""
    t, admin, main, west, p = _seed_scenario(db_session)
    tok = _login(client, "owner_rx")

    before = db_session.query(Product).filter(Product.id == p.id).one().stock_qty
    assert float(before) == 5.0
    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 5.0
    assert _movements(db_session, p.id) == []

    list_before = client.get("/api/products", headers=_auth(tok, main.id)).json()
    assert float(list_before[0]["stockQty"]) == 5.0

    r = _restock(client, tok, p.id, 3, branch_id=main.id)
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp["branch_id"] == main.id
    assert resp["resulting_qty"] == 8.0
    assert resp["previous_qty"] == 5.0
    assert resp["quantity_added"] == 3.0

    # 3. BranchProductStock becomes exactly 8 on the active branch.
    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 8.0
    # 10. Branch B remains unchanged.
    assert float(_bpg(db_session, west.id, p.id).stock_qty) == 0.0
    # 4. Product.stock_qty shadow = sum of branch stock.
    db_session.refresh(p)
    assert float(p.stock_qty) == 8.0
    # 7. Exactly one movement, tied to the active branch.
    movs = _movements(db_session, p.id)
    assert len(movs) == 1
    assert movs[0].change_qty == 3.0
    assert movs[0].branch_id == main.id

    # 5. Inventory list API immediately returns 8 for the active branch.
    list_after = client.get("/api/products", headers=_auth(tok, main.id)).json()
    assert float(list_after[0]["stockQty"]) == 8.0
    assert list_after[0]["branchId"] == main.id

    # 6. Edit panel API (restock response) returns 8.
    assert resp["resulting_qty"] == 8.0


def test_reopen_panel_without_save_does_not_increment(client, db_session):
    t, admin, main, west, p = _seed_scenario(db_session)
    tok = _login(client, "owner_rx")

    first = _restock(client, tok, p.id, 3, branch_id=main.id)
    assert first.status_code == 200
    movs_before_reopen = _movements(db_session, p.id)
    assert len(movs_before_reopen) == 1

    # Reopen the panel: fetch product details + list; no restock call.
    detail = client.get(f"/api/products/{p.id}", headers=_auth(tok, main.id)).json()
    _ = client.get("/api/products", headers=_auth(tok, main.id)).json()

    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 8.0
    assert len(_movements(db_session, p.id)) == 1


def test_second_intentional_receipt_changes_8_to_11_exactly_once(client, db_session):
    t, admin, main, west, p = _seed_scenario(db_session)
    tok = _login(client, "owner_rx")

    assert _restock(client, tok, p.id, 3, branch_id=main.id).status_code == 200
    assert _restock(client, tok, p.id, 3, branch_id=main.id).status_code == 200

    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 11.0
    assert float(_bpg(db_session, west.id, p.id).stock_qty) == 0.0
    movs = _movements(db_session, p.id)
    assert len(movs) == 2
    assert sum(float(m.change_qty) for m in movs) == 6.0
    db_session.refresh(p)
    assert float(p.stock_qty) == 11.0


def test_switching_branches_displays_each_branch_quantity(client, db_session):
    t, admin, main, west, p = _seed_scenario(db_session)
    # Give west some stock so the two branches differ.
    set_branch_stock(
        db_session, tenant_id=t.id, branch_id=west.id, product_id=p.id, quantity=2, reason="seed"
    )
    sync_legacy_product_stock(db_session, p.id)
    db_session.commit()
    tok = _login(client, "owner_rx")

    main_list = client.get("/api/products", headers=_auth(tok, main.id)).json()
    west_list = client.get("/api/products", headers=_auth(tok, west.id)).json()
    assert float(main_list[0]["stockQty"]) == 5.0
    assert main_list[0]["branchId"] == main.id
    assert float(west_list[0]["stockQty"]) == 2.0
    assert west_list[0]["branchId"] == west.id


def test_consolidated_total_returned_separately_from_branch_stock(client, db_session):
    t, admin, main, west, p = _seed_scenario(db_session)
    set_branch_stock(
        db_session, tenant_id=t.id, branch_id=west.id, product_id=p.id, quantity=2, reason="seed"
    )
    sync_legacy_product_stock(db_session, p.id)
    db_session.commit()
    tok = _login(client, "owner_rx")
    sw = client.post("/api/branches/switch", headers=_auth(tok), json={"scope": "all"})
    assert sw.status_code == 200, sw.text
    all_tok = sw.json()["access_token"]

    rows = client.get("/api/products?consolidated=true", headers=_auth(all_tok)).json()
    row = rows[0]
    # Branch availability is not presented as the consolidated total.
    assert row["stockQty"] is None
    assert row["branchId"] is None
    # Consolidated total is a separate field.
    assert float(row["totalStockQty"]) == 7.0
    breakdown = {b["branchId"]: float(b["quantity"]) for b in row["branchStock"]}
    assert breakdown[main.id] == 5.0
    assert breakdown[west.id] == 2.0


def test_failed_update_rolls_back_quantity_and_movement(client, db_session, monkeypatch):
    t, admin, main, west, p = _seed_scenario(db_session)
    tok = _login(client, "owner_rx")

    def boom(db, product_id):
        raise RuntimeError("forced sync failure")

    monkeypatch.setattr("app.inventory_service.sync_legacy_product_stock", boom)

    r = _restock(client, tok, p.id, 3, branch_id=main.id)
    # The endpoint rolls back on any exception.
    assert r.status_code == 500

    # Nothing persisted: quantity and movement both rolled back.
    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 5.0
    assert _movements(db_session, p.id) == []


def test_duplicate_submission_idempotent_no_double_increment(client, db_session):
    t, admin, main, west, p = _seed_scenario(db_session)
    tok = _login(client, "owner_rx")

    mid = "recv-once-0001"
    r1 = _restock(client, tok, p.id, 3, branch_id=main.id, movement_id=mid)
    assert r1.status_code == 200
    r2 = _restock(client, tok, p.id, 3, branch_id=main.id, movement_id=mid)
    assert r2.status_code == 200

    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 8.0
    assert len(_movements(db_session, p.id)) == 1