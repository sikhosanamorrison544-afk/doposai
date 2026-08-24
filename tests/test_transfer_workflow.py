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
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
