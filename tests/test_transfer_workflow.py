"""
Section 15 — inter-branch stock transfer workflow tests.

Covers the full DRAFT -> REQUESTED -> APPROVED -> DISPATCHED -> RECEIVED
lifecycle via the /api/transfers API: BranchProductStock stays authoritative,
Product.stock_qty remains the legacy shadow, approval only reserves, dispatch
moves stock out of source and releases the reservation, receipt moves stock
into the destination (partial accepted/damaged/missing supported), idempotency
keys work, tenant isolation holds, permissions are enforced, and a transfer
NEVER creates Sale / Payment / Expense / Withdrawal / JournalEntry rows.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth as auth_mod
from app.database import Base, get_db
from app.enterprise_models import Branch, BranchProductStock, StockTransfer, StockTransferItem
from app.inventory_service import set_branch_stock, sync_legacy_product_stock
from app.main import app as fastapi_app
from app.models import InventoryMovement, Product, SaleItem, User
from app.quotation_models import Tenant

import app.enterprise_models  # noqa: F401
import app.branch_models  # noqa: F401
import app.accounting_models  # noqa: F401

from app.branch_models import UserBranch


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


# --- production-schema-gap fixtures -----------------------------------------
#
# The production `stock_transfers` / `stock_transfer_items` tables were created
# before the ORM models gained the lifecycle/notes/idempotency columns. Those
# tables are recreated here in their legacy shape so the regression tests can
# reproduce the exact `UndefinedColumn ... request_notes` 500 and prove the
# additive branch migration repairs it.

LEGACY_STOCK_TRANSFERS_DDL = """
CREATE TABLE stock_transfers (
    id INTEGER NOT NULL PRIMARY KEY,
    tenant_id INTEGER,
    transfer_number VARCHAR(50),
    from_branch_id INTEGER,
    to_branch_id INTEGER,
    status VARCHAR(32),
    notes TEXT,
    created_by INTEGER,
    sent_at DATETIME,
    received_at DATETIME,
    received_by INTEGER,
    created_at DATETIME,
    updated_at DATETIME
)
"""

LEGACY_STOCK_TRANSFER_ITEMS_DDL = """
CREATE TABLE stock_transfer_items (
    id INTEGER NOT NULL PRIMARY KEY,
    stock_transfer_id INTEGER,
    product_id INTEGER,
    product_name VARCHAR(120),
    quantity FLOAT,
    quantity_received FLOAT
)
"""


@pytest.fixture()
def legacy_db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE stock_transfer_items"))
        conn.execute(text("DROP TABLE stock_transfers"))
        conn.execute(text(LEGACY_STOCK_TRANSFERS_DDL))
        conn.execute(text(LEGACY_STOCK_TRANSFER_ITEMS_DDL))
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = Session()
    db._legacy_engine = engine
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def legacy_client(legacy_db_session):
    def _override():
        try:
            yield legacy_db_session
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = _override
    with TestClient(fastapi_app, raise_server_exceptions=False) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


# --- helpers ---------------------------------------------------------------


def _hash(pw="AdminPass1234"):
    return auth_mod.get_password_hash(pw)


def _tenant(db, name="Transfer Shop"):
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


def _product(db, tenant_id, name, cost=4.0):
    p = Product(
        name=name,
        barcode=f"B-{uuid.uuid4().hex[:10]}",
        selling_price=10,
        cost_price=cost,
        stock_qty=0,
        tenant_id=tenant_id,
    )
    db.add(p)
    db.flush()
    return p


def _bpg(db, branch_id, product_id):
    return (
        db.query(BranchProductStock)
        .filter(
            BranchProductStock.branch_id == branch_id,
            BranchProductStock.product_id == product_id,
        )
        .one()
    )


def _movements(db, product_id=None, movement_type=None):
    q = db.query(InventoryMovement)
    if product_id is not None:
        q = q.filter(InventoryMovement.product_id == product_id)
    if movement_type is not None:
        q = q.filter(InventoryMovement.movement_type == movement_type)
    return q.order_by(InventoryMovement.id.asc()).all()


def _login(client, username):
    r = client.post(
        "/api/auth/token",
        data={"username": username, "password": "AdminPass1234"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed_shop(db, west_p1=0):
    """Tenant with Main+West branches; p1 at Main 10, p2 at Main 20."""
    t = _tenant(db)
    admin = _user(db, t.id, "owner_xfer", role="admin")
    main = _branch(db, t.id, "Main Branch", "MAIN", is_default=True)
    west = _branch(db, t.id, "West", "WEST")
    p1 = _product(db, t.id, "Cement 50kg", cost=4)
    p2 = _product(db, t.id, "Putty 5kg", cost=6)
    set_branch_stock(db, tenant_id=t.id, branch_id=main.id, product_id=p1.id, quantity=10, reason="seed")
    set_branch_stock(db, tenant_id=t.id, branch_id=main.id, product_id=p2.id, quantity=20, reason="seed")
    set_branch_stock(db, tenant_id=t.id, branch_id=west.id, product_id=p1.id, quantity=west_p1, reason="seed")
    db.commit()
    return t, admin, main, west, p1, p2


def _create(client, tok, from_id, to_id, items=None, client_transfer_id=None, notes=None):
    payload = {"from_branch_id": from_id, "to_branch_id": to_id, "notes": notes}
    if items is not None:
        payload["items"] = items
    if client_transfer_id:
        payload["client_transfer_id"] = client_transfer_id
    return client.post("/api/transfers", headers=_auth(tok), json=payload)


def _request(client, tok, tid, notes=None):
    return client.post(f"/api/transfers/{tid}/request", headers=_auth(tok), json={"notes": notes})


def _approve(client, tok, tid, notes=None):
    return client.post(f"/api/transfers/{tid}/approve", headers=_auth(tok), json={"notes": notes})


def _dispatch(client, tok, tid, notes=None):
    return client.post(f"/api/transfers/{tid}/dispatch", headers=_auth(tok), json={"notes": notes})


def _receive(client, tok, tid, lines, notes=None, client_movement_id=None):
    payload = {"lines": lines, "notes": notes}
    if client_movement_id:
        payload["client_movement_id"] = client_movement_id
    return client.post(f"/api/transfers/{tid}/receive", headers=_auth(tok), json=payload)


def _reject(client, tok, tid, reason="No stock"):
    return client.post(f"/api/transfers/{tid}/reject", headers=_auth(tok), json={"reason": reason})


def _cancel(client, tok, tid, reason=None):
    return client.post(f"/api/transfers/{tid}/cancel", headers=_auth(tok), json={"reason": reason})


def _full_transfer(client, tok, main, west, p, qty):
    """Create -> request -> approve -> dispatch for a single product; returns tid + item id."""
    r = _create(client, tok, main.id, west.id, items=[{"product_id": p.id, "quantity": qty}])
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert _request(client, tok, tid).status_code == 200
    assert _approve(client, tok, tid).status_code == 200
    rd = _dispatch(client, tok, tid)
    assert rd.status_code == 200, rd.text
    return tid, rd.json()["items"][0]["id"]


# --- draft editing ---------------------------------------------------------


def test_create_draft_manage_items_and_delete(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")

    r = _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 4}], notes="restock west")
    assert r.status_code == 201, r.text
    body = r.json()
    tid = body["id"]
    assert body["status"] == "draft"
    assert body["from_branch_id"] == main.id
    assert body["to_branch_id"] == west.id
    assert body["notes"] == "restock west"
    assert body["transfer_number"].startswith("TR-")
    assert len(body["items"]) == 1
    assert float(body["items"][0]["quantity_requested"]) == 4.0
    item_id = body["items"][0]["id"]

    # Draft editing: add, update, then remove an item.
    r2 = client.post(
        f"/api/transfers/{tid}/items", headers=_auth(tok), json={"product_id": p2.id, "quantity": 5}
    )
    assert r2.status_code == 201, r2.text
    assert len(r2.json()["items"]) == 2

    r3 = client.put(
        f"/api/transfers/{tid}/items/{item_id}", headers=_auth(tok), json={"quantity": 7}
    )
    assert r3.status_code == 200, r3.text
    assert float(r3.json()["items"][0]["quantity_requested"]) == 7.0

    r4 = client.patch(f"/api/transfers/{tid}", headers=_auth(tok), json={"notes": "updated"})
    assert r4.status_code == 200, r4.text
    assert r4.json()["notes"] == "updated"

    # No stock impact while drafting.
    assert float(_bpg(db_session, main.id, p1.id).stock_qty) == 10.0
    assert float(_bpg(db_session, main.id, p1.id).reserved_qty) == 0.0

    r5 = client.delete(f"/api/transfers/{tid}/items/{item_id}", headers=_auth(tok))
    assert r5.status_code == 204
    assert len(_get_transfer(client, tok, tid)["items"]) == 1

    r6 = client.delete(f"/api/transfers/{tid}", headers=_auth(tok))
    assert r6.status_code == 204
    assert db_session.query(StockTransfer).filter(StockTransfer.id == tid).first() is None
    assert db_session.query(StockTransferItem).filter(StockTransferItem.stock_transfer_id == tid).count() == 0


def _get_transfer(client, tok, tid):
    r = client.get(f"/api/transfers/{tid}", headers=_auth(tok))
    assert r.status_code == 200, r.text
    return r.json()


# --- full lifecycle --------------------------------------------------------


def test_full_lifecycle_moves_stock_between_branches(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    tid, item_id = _full_transfer(client, tok, main, west, p1, 4)

    # Dispatched: source on-hand down by 4, reservation gone, dest not credited.
    src = _bpg(db_session, main.id, p1.id)
    assert float(src.stock_qty) == 6.0
    assert float(src.reserved_qty) == 0.0
    dest = _bpg(db_session, west.id, p1.id)
    assert float(dest.stock_qty) == 0.0  # not credited yet
    db_session.refresh(p1)
    assert float(p1.stock_qty) == 6.0  # legacy shadow excludes in-transit

    disp = _movements(db_session, p1.id, "TRANSFER_DISPATCH")
    assert len(disp) == 1
    assert float(disp[0].change_qty) == -4.0
    assert disp[0].branch_id == main.id
    assert disp[0].reference_type == "STOCK_TRANSFER"
    assert disp[0].reference_id == tid

    # Receive fully: destination up by 4, status received.
    rr = _receive(
        client, tok, tid, [{"item_id": item_id, "accepted": 4, "damaged": 0, "missing": 0}]
    )
    assert rr.status_code == 200, rr.text
    assert rr.json()["status"] == "received"
    assert float(_bpg(db_session, west.id, p1.id).stock_qty) == 4.0
    db_session.refresh(p1)
    assert float(p1.stock_qty) == 10.0

    rec = _movements(db_session, p1.id, "TRANSFER_RECEIPT")
    assert len(rec) == 1
    assert float(rec[0].change_qty) == 4.0
    assert rec[0].branch_id == west.id
    assert rec[0].reference_id == tid

    detail = _get_transfer(client, tok, tid)
    assert detail["requested_by_id"] == admin.id
    assert detail["approved_by_id"] == admin.id
    assert detail["dispatched_by_id"] == admin.id
    assert detail["received_by"] == admin.id
    assert detail["dispatched_at"] is not None
    assert detail["received_at"] is not None
    it = detail["items"][0]
    assert float(it["quantity_dispatched"]) == 4.0
    assert float(it["quantity_received"]) == 4.0
    assert float(it["in_transit_quantity"]) == 0.0
    assert float(it["dispatched_value"]) == 16.0  # 4 units x cost 4
    assert float(it["received_value"]) == 16.0


# --- reservation semantics -------------------------------------------------


def test_approve_reserves_stock_but_does_not_move_it(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    r = _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 4}])
    tid = r.json()["id"]
    assert _request(client, tok, tid).status_code == 200
    ra = _approve(client, tok, tid)
    assert ra.status_code == 200, ra.text
    assert ra.json()["status"] == "approved"
    assert float(ra.json()["items"][0]["quantity_approved"]) == 4.0

    src = _bpg(db_session, main.id, p1.id)
    assert float(src.stock_qty) == 10.0  # on-hand unchanged
    assert float(src.reserved_qty) == 4.0
    # Approval must not write any inventory movement.
    assert _movements(db_session, p1.id, "TRANSFER_DISPATCH") == []
    assert _movements(db_session, p1.id, "TRANSFER_RECEIPT") == []


def test_approve_insufficient_available_returns_409_and_rolls_back(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    r1 = _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 8}])
    r2 = _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 5}])
    tid1, tid2 = r1.json()["id"], r2.json()["id"]

    assert _request(client, tok, tid1).status_code == 200
    assert _approve(client, tok, tid1).status_code == 200
    assert float(_bpg(db_session, main.id, p1.id).reserved_qty) == 8.0

    assert _request(client, tok, tid2).status_code == 200
    ra = _approve(client, tok, tid2)
    assert ra.status_code == 409, ra.text
    assert "Insufficient" in ra.json()["detail"]

    # Failed approval reserved nothing and did not advance status.
    assert float(_bpg(db_session, main.id, p1.id).reserved_qty) == 8.0
    assert db_session.query(StockTransfer).filter(StockTransfer.id == tid2).one().status == "requested"


def test_cancel_approved_releases_reservation(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    r = _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 4}])
    tid = r.json()["id"]
    assert _request(client, tok, tid).status_code == 200
    assert _approve(client, tok, tid).status_code == 200
    assert float(_bpg(db_session, main.id, p1.id).reserved_qty) == 4.0

    rc = _cancel(client, tok, tid, reason="changed mind")
    assert rc.status_code == 200, rc.text
    assert rc.json()["status"] == "cancelled"
    assert rc.json()["cancellation_reason"] == "changed mind"
    assert float(_bpg(db_session, main.id, p1.id).reserved_qty) == 0.0
    assert float(_bpg(db_session, main.id, p1.id).stock_qty) == 10.0


def test_reject_requested_transfer(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    r = _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 4}])
    tid = r.json()["id"]
    assert _request(client, tok, tid).status_code == 200
    rr = _reject(client, tok, tid, reason="not needed")
    assert rr.status_code == 200, rr.text
    assert rr.json()["status"] == "rejected"
    assert rr.json()["rejection_reason"] == "not needed"
    # No stock/reservation side effects.
    assert float(_bpg(db_session, main.id, p1.id).reserved_qty) == 0.0


def test_dispatch_requires_approved_and_receive_requires_dispatched(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    r = _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 4}])
    tid = r.json()["id"]

    # Dispatch from DRAFT is invalid.
    assert _dispatch(client, tok, tid).status_code == 409
    # Receive from DRAFT is invalid.
    assert _receive(client, tok, tid, [{"item_id": 1, "accepted": 1}]).status_code == 409

    assert _request(client, tok, tid).status_code == 200
    assert _dispatch(client, tok, tid).status_code == 409  # not yet approved

    assert _approve(client, tok, tid).status_code == 200
    # Receive before dispatch is invalid.
    assert _receive(client, tok, tid, [{"item_id": 1, "accepted": 1}]).status_code == 409

    rd = _dispatch(client, tok, tid)
    assert rd.status_code == 200, rd.text
    # Receiving more than dispatched is rejected.
    item_id = rd.json()["items"][0]["id"]
    rr = _receive(client, tok, tid, [{"item_id": item_id, "accepted": 99}])
    assert rr.status_code == 409
    assert "exceed dispatched quantity" in rr.json()["detail"]


# --- partial receipt -------------------------------------------------------


def test_partial_receive_accepted_damaged_missing(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    tid, item_id = _full_transfer(client, tok, main, west, p1, 10)

    # First event: 4 good + 1 damaged + 1 missing = 6 accounted, still in transit.
    r1 = _receive(
        client, tok, tid,
        [{"item_id": item_id, "accepted": 4, "damaged": 1, "missing": 1}],
        client_movement_id="rx-part-1",
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "dispatched"  # not complete yet
    it = r1.json()["items"][0]
    assert float(it["quantity_received"]) == 4.0
    assert float(it["quantity_damaged"]) == 1.0
    assert float(it["quantity_missing"]) == 1.0
    assert float(it["in_transit_quantity"]) == 4.0
    # Only good units entered destination on-hand.
    assert float(_bpg(db_session, west.id, p1.id).stock_qty) == 4.0
    assert float(_bpg(db_session, main.id, p1.id).stock_qty) == 0.0

    # Second event: remaining 4 accepted -> complete.
    r2 = _receive(
        client, tok, tid,
        [{"item_id": item_id, "accepted": 4, "damaged": 0, "missing": 0}],
        client_movement_id="rx-part-2",
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "received"
    assert float(r2.json()["items"][0]["in_transit_quantity"]) == 0.0
    assert float(_bpg(db_session, west.id, p1.id).stock_qty) == 8.0
    db_session.refresh(p1)
    assert float(p1.stock_qty) == 8.0  # legacy shadow = physical branch stock only

    assert len(_movements(db_session, p1.id, "TRANSFER_RECEIPT")) == 2
    assert float(sum(m.change_qty for m in _movements(db_session, p1.id, "TRANSFER_RECEIPT"))) == 8.0


# --- idempotency -----------------------------------------------------------


def test_duplicate_create_by_client_transfer_id_is_idempotent(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    cid = f"xfer-{uuid.uuid4().hex[:8]}"
    payload_items = [{"product_id": p1.id, "quantity": 4}]
    r1 = _create(client, tok, main.id, west.id, items=payload_items, client_transfer_id=cid)
    r2 = _create(client, tok, main.id, west.id, items=payload_items, client_transfer_id=cid)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert db_session.query(StockTransfer).count() == 1


def test_duplicate_receive_by_client_movement_id_is_idempotent(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    tid, item_id = _full_transfer(client, tok, main, west, p1, 4)
    line = [{"item_id": item_id, "accepted": 4, "damaged": 0, "missing": 0}]
    r1 = _receive(client, tok, tid, line, client_movement_id="rx-once")
    r2 = _receive(client, tok, tid, line, client_movement_id="rx-once")
    assert r1.status_code == 200 and r2.status_code == 200
    assert float(_bpg(db_session, west.id, p1.id).stock_qty) == 4.0
    assert len(_movements(db_session, p1.id, "TRANSFER_RECEIPT")) == 1


def test_dispatch_is_idempotent_on_retry(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    tid, item_id = _full_transfer(client, tok, main, west, p1, 4)
    # Retry dispatch after success: idempotent, no double movement.
    rd2 = _dispatch(client, tok, tid)
    assert rd2.status_code == 200, rd2.text
    assert rd2.json()["status"] == "dispatched"
    assert len(_movements(db_session, p1.id, "TRANSFER_DISPATCH")) == 1


# --- guards / permissions --------------------------------------------------


def test_same_branch_and_cross_tenant_guards(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    # Another tenant with its own branches and a product that shares the same id space.
    t2 = _tenant(db_session, "Other Shop")
    other_admin = _user(db_session, t2.id, "owner_other", role="admin")
    other_main = _branch(db_session, t2.id, "Other Main", "OM")
    other_west = _branch(db_session, t2.id, "Other West", "OW")
    other_p = _product(db_session, t2.id, "Other Product")
    set_branch_stock(db_session, tenant_id=t2.id, branch_id=other_main.id, product_id=other_p.id, quantity=5, reason="seed")
    db_session.commit()

    tok = _login(client, "owner_xfer")
    tok2 = _login(client, "owner_other")

    # Same branch source == destination.
    assert _create(client, tok, main.id, main.id, items=[{"product_id": p1.id, "quantity": 1}]).status_code == 400

    # Cross-tenant transfer (user2 using tenant1's branches): foreign branch 404.
    r = _create(client, tok2, other_main.id, main.id, items=[{"product_id": other_p.id, "quantity": 1}])
    assert r.status_code == 404

    # A transfer created in tenant1 is invisible to tenant2 (404 detail).
    tid = _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 1}]).json()["id"]
    assert client.get(f"/api/transfers/{tid}", headers=_auth(tok2)).status_code == 404
    # Tenant2 cannot add tenant1 products to their draft.
    t2_draft = _create(client, tok2, other_main.id, other_west.id)
    assert t2_draft.status_code == 201
    r_add = client.post(
        f"/api/transfers/{t2_draft.json()['id']}/items", headers=_auth(tok2),
        json={"product_id": p1.id, "quantity": 1},
    )
    assert r_add.status_code == 404  # product belongs to tenant1


def test_cashier_cannot_run_transfer_workflow(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    cashier = _user(db_session, t.id, "cash_xfer", role="cashier")
    db_session.commit()
    tok_c = _login(client, "cash_xfer")
    tok_a = _login(client, "owner_xfer")

    # Cashiers cannot even list transfers (no BRANCH_TRANSFER_VIEW).
    assert client.get("/api/transfers", headers=_auth(tok_c)).status_code == 403
    assert _create(client, tok_c, main.id, west.id, items=[{"product_id": p1.id, "quantity": 1}]).status_code == 403

    tid = _create(client, tok_a, main.id, west.id, items=[{"product_id": p1.id, "quantity": 1}]).json()["id"]
    assert _request(client, tok_c, tid).status_code == 403
    assert _approve(client, tok_c, tid).status_code == 403
    assert _dispatch(client, tok_c, tid).status_code == 403
    assert _receive(client, tok_c, tid, [{"item_id": 1, "accepted": 1}]).status_code == 403


def test_list_filters_and_branch_visibility(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    north = _branch(db_session, t.id, "North", "NORTH")
    supervisor = _user(db_session, t.id, "sup_xfer", role="supervisor")
    db_session.add(
        UserBranch(user_id=supervisor.id, branch_id=north.id, tenant_id=t.id, role="manager", is_active=True, is_default=True)
    )
    db_session.commit()
    tok = _login(client, "owner_xfer")
    tok_s = _login(client, "sup_xfer")

    t1 = _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 4}]).json()["id"]
    _request(client, tok, t1)
    _approve(client, tok, t1)
    t2 = _create(client, tok, main.id, west.id, items=[{"product_id": p2.id, "quantity": 5}]).json()["id"]

    # Admin sees both; filters by status and source branch work.
    rows = client.get("/api/transfers", headers=_auth(tok)).json()
    assert {r["id"] for r in rows} == {t1, t2}
    rows = client.get("/api/transfers?status=approved", headers=_auth(tok)).json()
    assert [r["id"] for r in rows] == [t1]
    rows = client.get(f"/api/transfers?from_branch_id={main.id}", headers=_auth(tok)).json()
    assert len(rows) == 2

    # Supervisor with access only to North cannot see Main<->West transfers.
    assert client.get("/api/transfers", headers=_auth(tok_s)).json() == []
    assert client.get(f"/api/transfers/{t1}", headers=_auth(tok_s)).status_code == 404


def test_edit_locked_after_request(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    r = _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 4}])
    tid = r.json()["id"]
    item_id = r.json()["items"][0]["id"]
    assert _request(client, tok, tid).status_code == 200

    assert client.post(
        f"/api/transfers/{tid}/items", headers=_auth(tok), json={"product_id": p2.id, "quantity": 1}
    ).status_code == 409
    assert client.put(
        f"/api/transfers/{tid}/items/{item_id}", headers=_auth(tok), json={"quantity": 9}
    ).status_code == 409
    assert client.delete(f"/api/transfers/{tid}", headers=_auth(tok)).status_code == 409
    assert client.patch(f"/api/transfers/{tid}", headers=_auth(tok), json={"notes": "x"}).status_code == 409


# --- financial isolation ---------------------------------------------------


def test_transfers_never_create_financial_rows(client, db_session):
    from app.accounting_models import JournalEntry
    from app.models import Expense, Payment, Sale, Withdrawal

    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")

    # Two full cycles (one with damaged/missing, one fully received).
    tid1, it1 = _full_transfer(client, tok, main, west, p1, 10)
    _receive(client, tok, tid1, [{"item_id": it1, "accepted": 8, "damaged": 1, "missing": 1}], client_movement_id="fin-rx-1")
    tid2, it2 = _full_transfer(client, tok, main, west, p2, 5)
    _receive(client, tok, tid2, [{"item_id": it2, "accepted": 5}], client_movement_id="fin-rx-2")

    assert db_session.query(Sale).count() == 0
    assert db_session.query(SaleItem).count() == 0
    assert db_session.query(Payment).count() == 0
    assert db_session.query(Expense).count() == 0
    assert db_session.query(Withdrawal).count() == 0
    assert db_session.query(JournalEntry).count() == 0


def test_cannot_cancel_after_dispatch(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    tid, item_id = _full_transfer(client, tok, main, west, p1, 4)
    assert _cancel(client, tok, tid).status_code == 409


# --- GET /api/transfers listing regression tests -----------------------------


def test_list_empty_returns_200(client, db_session):
    """Empty transfer list returns a valid 200 (empty paginated list)."""
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    r = client.get("/api/transfers", headers=_auth(tok))
    assert r.status_code == 200, r.text
    assert r.json() == []
    # Also valid with explicit pagination params.
    r = client.get("/api/transfers?limit=10&offset=0", headers=_auth(tok))
    assert r.status_code == 200
    assert r.json() == []


def test_list_serializes_existing_transfer(client, db_session):
    """Existing transfer rows serialize successfully in the list response."""
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    tid = _create(
        client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 4}], notes="restock west"
    ).json()["id"]

    r = client.get("/api/transfers", headers=_auth(tok))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == tid
    assert row["status"] == "draft"
    assert row["transfer_number"].startswith("TR-")
    assert row["from_branch_id"] == main.id
    assert row["to_branch_id"] == west.id
    assert row["notes"] == "restock west"
    assert row["created_by"] == admin.id
    assert len(row["items"]) == 1
    assert row["items"][0]["product_name"] == p1.name


def test_nullable_legacy_fields_serialize_safely(client, db_session):
    """Fully-null lifecycle/notes fields on existing rows never cause a 500."""
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    tid = _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 4}]).json()["id"]

    # Force every legacy-nullable transfer field to NULL (as an old production
    # row would have before the column backfills).
    db_session.query(StockTransfer).filter(StockTransfer.id == tid).update(
        {
            StockTransfer.request_notes: None,
            StockTransfer.approval_notes: None,
            StockTransfer.dispatch_notes: None,
            StockTransfer.receipt_notes: None,
            StockTransfer.rejection_reason: None,
            StockTransfer.cancellation_reason: None,
            StockTransfer.requested_by_id: None,
            StockTransfer.approved_by_id: None,
            StockTransfer.dispatched_by_id: None,
            StockTransfer.received_by: None,
            StockTransfer.rejected_by_id: None,
            StockTransfer.cancelled_by_id: None,
            StockTransfer.requested_at: None,
            StockTransfer.approved_at: None,
            StockTransfer.sent_at: None,
            StockTransfer.received_at: None,
            StockTransfer.rejected_at: None,
            StockTransfer.cancelled_at: None,
        }
    )
    db_session.query(StockTransferItem).filter(StockTransferItem.stock_transfer_id == tid).update(
        {
            StockTransferItem.approved_quantity: None,
            StockTransferItem.quantity_dispatched: None,
            StockTransferItem.quantity_damaged: None,
            StockTransferItem.quantity_missing: None,
            StockTransferItem.unit_cost_snapshot: None,
            StockTransferItem.notes: None,
            StockTransferItem.request_notes: None,
            StockTransferItem.dispatch_notes: None,
            StockTransferItem.receipt_notes: None,
        }
    )
    db_session.commit()

    r = client.get("/api/transfers", headers=_auth(tok))
    assert r.status_code == 200, r.text
    row = r.json()[0]
    for key in (
        "request_notes",
        "approval_notes",
        "dispatch_notes",
        "receipt_notes",
        "rejection_reason",
        "cancellation_reason",
        "requested_by_id",
        "approved_by_id",
        "dispatched_by_id",
        "received_by",
        "rejected_by_id",
        "cancelled_by_id",
        "requested_at",
        "approved_at",
        "dispatched_at",
        "received_at",
        "rejected_at",
        "cancelled_at",
    ):
        assert row[key] is None, f"{key} should be null"
    item = row["items"][0]
    assert float(item["quantity_dispatched"]) == 0.0
    assert float(item["quantity_damaged"]) == 0.0
    assert float(item["quantity_missing"]) == 0.0
    assert item["unit_cost_snapshot"] is None


def _insert_legacy_transfer(db, tenant_id, from_branch_id, to_branch_id, created_by, product_id):
    """Insert a transfer row using only the pre-multi-branch (legacy) columns."""
    now = datetime.utcnow()
    db.execute(
        text(
            "INSERT INTO stock_transfers "
            "(tenant_id, transfer_number, from_branch_id, to_branch_id, status, notes, "
            " created_by, created_at, updated_at) "
            "VALUES (:tid, 'TR-LEGACY-1', :fb, :tb, 'draft', 'legacy note', :cb, :now, :now)"
        ),
        {"tid": tenant_id, "fb": from_branch_id, "tb": to_branch_id, "cb": created_by, "now": now},
    )
    tid = db.execute(text("SELECT last_insert_rowid()")).scalar()
    db.execute(
        text(
            "INSERT INTO stock_transfer_items "
            "(stock_transfer_id, product_id, product_name, quantity, quantity_received) "
            "VALUES (:tid, :pid, 'Legacy Item', 3.0, 0.0)"
        ),
        {"tid": tid, "pid": product_id},
    )
    db.commit()
    return tid


def test_legacy_schema_gap_reproduced_then_repaired(legacy_client, legacy_db_session):
    """Reproduce the production UndefinedColumn 500, then prove the additive
    branch migration repairs the schema and the list endpoint returns 200 with
    the legacy row's nullable fields serialized safely."""
    import migrate_branches as mb

    t, admin, main, west, p1, p2 = _seed_shop(legacy_db_session)
    legacy_tid = _insert_legacy_transfer(legacy_db_session, t.id, main.id, west.id, admin.id, p1.id)
    tok = _login(legacy_client, "owner_xfer")

    # Reproduction: stale production-style schema makes GET /api/transfers 500.
    before = legacy_client.get("/api/transfers", headers=_auth(tok))
    assert before.status_code == 500, before.text

    # Repair with the exact additive migration path used in production.
    engine = legacy_db_session._legacy_engine
    mb.INCLUDE_TRANSFERS = True
    try:
        report = mb.apply_migration(engine)
    finally:
        mb.INCLUDE_TRANSFERS = False

    assert "stock_transfers.request_notes" in report["added_columns"]
    assert "stock_transfers.version" in report["added_columns"]
    assert "stock_transfer_items.created_at" in report["added_columns"]
    assert mb.missing_required_schema(engine) == []

    legacy_db_session.rollback()  # end any transaction left from apply_migration

    # Same request now returns 200; the legacy row serializes with NULL new fields.
    r = legacy_client.get("/api/transfers", headers=_auth(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    row = body[0]
    assert row["id"] == legacy_tid
    assert row["transfer_number"] == "TR-LEGACY-1"
    assert row["status"] == "draft"
    assert row["notes"] == "legacy note"
    assert row["created_at"] is not None
    assert row["request_notes"] is None
    assert row["approval_notes"] is None
    assert row["dispatch_notes"] is None
    assert row["receipt_notes"] is None
    assert row["rejection_reason"] is None
    assert row["cancellation_reason"] is None
    assert row["requested_by_id"] is None
    assert row["approved_by_id"] is None
    assert row["dispatched_by_id"] is None
    assert row["cancelled_at"] is None
    item = row["items"][0]
    assert item["product_name"] == "Legacy Item"
    assert float(item["quantity_dispatched"]) == 0.0
    assert float(item["quantity_damaged"]) == 0.0
    assert float(item["quantity_missing"]) == 0.0
    assert item["unit_cost_snapshot"] is None


def test_owner_and_admin_can_list(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    owner = _user(db_session, t.id, "owner_list", role="owner")
    db_session.commit()
    tok_o = _login(client, "owner_list")
    tok_a = _login(client, "owner_xfer")  # admin role

    r_o = client.get("/api/transfers", headers=_auth(tok_o))
    assert r_o.status_code == 200
    r_a = client.get("/api/transfers", headers=_auth(tok_a))
    assert r_a.status_code == 200
    assert r_o.json() == []
    assert r_a.json() == []


def test_supervisor_sees_only_accessible_branch_transfers(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    north = _branch(db_session, t.id, "North", "NORTH")
    supervisor = _user(db_session, t.id, "sup_list", role="supervisor")
    db_session.add(
        UserBranch(
            user_id=supervisor.id, branch_id=north.id, tenant_id=t.id,
            role="manager", is_active=True, is_default=True,
        )
    )
    db_session.commit()
    tok = _login(client, "owner_xfer")
    tok_s = _login(client, "sup_list")

    t_north = _create(client, tok, north.id, main.id, items=[{"product_id": p1.id, "quantity": 2}]).json()["id"]
    t_west = _create(client, tok, main.id, west.id, items=[{"product_id": p2.id, "quantity": 3}]).json()["id"]

    # Supervisor only has access to North: sees the transfer touching North,
    # never the Main<->West one.
    rows = client.get("/api/transfers", headers=_auth(tok_s)).json()
    assert [r["id"] for r in rows] == [t_north]
    assert client.get(f"/api/transfers/{t_west}", headers=_auth(tok_s)).status_code == 404


def test_cashier_list_receives_403(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    cashier = _user(db_session, t.id, "cash_list", role="cashier")
    db_session.commit()
    tok_c = _login(client, "cash_list")
    assert client.get("/api/transfers", headers=_auth(tok_c)).status_code == 403


def test_cross_tenant_transfers_hidden_from_list(client, db_session):
    t1, admin1, main1, west1, p1, p2 = _seed_shop(db_session)
    t2 = _tenant(db_session, "Other Tenant Shop")
    admin2 = _user(db_session, t2.id, "owner_other", role="admin")
    main2 = _branch(db_session, t2.id, "Main2", "MAIN2", is_default=True)
    west2 = _branch(db_session, t2.id, "West2", "WEST2")
    p3 = _product(db_session, t2.id, "Other Product")
    db_session.commit()

    tok1 = _login(client, "owner_xfer")
    tok2 = _login(client, "owner_other")

    tid1 = _create(client, tok1, main1.id, west1.id, items=[{"product_id": p1.id, "quantity": 1}]).json()["id"]
    tid2 = _create(client, tok2, main2.id, west2.id, items=[{"product_id": p3.id, "quantity": 1}]).json()["id"]

    assert [r["id"] for r in client.get("/api/transfers", headers=_auth(tok1)).json()] == [tid1]
    assert [r["id"] for r in client.get("/api/transfers", headers=_auth(tok2)).json()] == [tid2]
    # Cross-tenant detail reads stay hidden as well.
    assert client.get(f"/api/transfers/{tid2}", headers=_auth(tok1)).status_code == 404
    assert client.get(f"/api/transfers/{tid1}", headers=_auth(tok2)).status_code == 404


def test_list_pagination_and_status_filters(client, db_session):
    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    drafts = []
    for _ in range(3):
        drafts.append(
            _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 1}]).json()["id"]
        )
    # Move the first draft to "requested" so a status filter has a target.
    _request(client, tok, drafts[0])

    page1 = client.get("/api/transfers?limit=2&offset=0", headers=_auth(tok)).json()
    page2 = client.get("/api/transfers?limit=2&offset=2", headers=_auth(tok)).json()
    assert len(page1) == 2
    assert len(page2) == 1
    assert [r["id"] for r in page1 + page2] == sorted(drafts, reverse=True)

    req = client.get("/api/transfers?status=requested", headers=_auth(tok)).json()
    assert [r["id"] for r in req] == [drafts[0]]
    assert len(client.get("/api/transfers", headers=_auth(tok)).json()) == 3


def test_listing_does_not_mutate_database(client, db_session):
    from app.accounting_models import JournalEntry
    from app.models import InventoryMovement

    t, admin, main, west, p1, p2 = _seed_shop(db_session)
    tok = _login(client, "owner_xfer")
    _create(client, tok, main.id, west.id, items=[{"product_id": p1.id, "quantity": 4}])

    counters = {
        "transfers": db_session.query(StockTransfer).count(),
        "items": db_session.query(StockTransferItem).count(),
        "movements": db_session.query(InventoryMovement).count(),
        "journal": db_session.query(JournalEntry).count(),
    }
    r = client.get("/api/transfers", headers=_auth(tok))
    assert r.status_code == 200
    assert db_session.query(StockTransfer).count() == counters["transfers"]
    assert db_session.query(StockTransferItem).count() == counters["items"]
    assert db_session.query(InventoryMovement).count() == counters["movements"]
    assert db_session.query(JournalEntry).count() == counters["journal"]
