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


# --- Exact 1 + 1 = 2 regression (not 3) ------------------------------------


def _seed_tape(db_session, stock=1.0):
    t = _tenant(db_session, name="Tape Shop")
    admin = _user(db_session, t.id, "tape_admin", role="admin")
    main = _branch(db_session, t.id, "Main Branch", "MAIN", is_default=True)
    p = Product(
        name="Tape Measure",
        barcode="TAPE-1",
        selling_price=10,
        cost_price=4,
        stock_qty=stock,
        tenant_id=t.id,
    )
    db_session.add(p)
    db_session.flush()
    seed_main_branch_from_legacy(db_session, tenant_id=t.id, branch_id=main.id, product=p)
    sync_legacy_product_stock(db_session, p.id)
    db_session.commit()
    return t, admin, main, p


def test_restock_one_plus_one_equals_two_not_three(client, db_session):
    """Acceptance: stock 1, receive 1 → exactly 2 with one InventoryMovement."""
    t, admin, main, p = _seed_tape(db_session, stock=1.0)
    tok = _login(client, "tape_admin")

    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 1.0
    before_movs = len(_movements(db_session, p.id))

    r = _restock(client, tok, p.id, 1, branch_id=main.id, movement_id="tape-recv-1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["previous_qty"] == 1.0
    assert body["quantity_added"] == 1.0
    assert body["resulting_qty"] == 2.0

    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 2.0
    db_session.refresh(p)
    assert float(p.stock_qty) == 2.0
    movs = _movements(db_session, p.id)
    assert len(movs) == before_movs + 1
    assert float(movs[-1].change_qty) == 1.0


def test_restock_larger_receipt_10_plus_5(client, db_session):
    t, admin, main, p = _seed_tape(db_session, stock=10.0)
    tok = _login(client, "tape_admin")

    r = _restock(client, tok, p.id, 5, branch_id=main.id)
    assert r.status_code == 200, r.text
    assert r.json()["resulting_qty"] == 15.0
    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 15.0
    assert len(_movements(db_session, p.id)) == 1


def test_restock_rejects_zero_and_negative(client, db_session):
    t, admin, main, p = _seed_tape(db_session, stock=1.0)
    tok = _login(client, "tape_admin")

    zero = _restock(client, tok, p.id, 0, branch_id=main.id)
    assert zero.status_code in (400, 422)

    neg = _restock(client, tok, p.id, -1, branch_id=main.id)
    assert neg.status_code in (400, 422)

    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 1.0
    assert _movements(db_session, p.id) == []


def test_one_request_one_increment_one_movement(client, db_session):
    t, admin, main, p = _seed_tape(db_session, stock=1.0)
    tok = _login(client, "tape_admin")

    r = _restock(client, tok, p.id, 1, branch_id=main.id, movement_id="single-action")
    assert r.status_code == 200
    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 2.0
    assert len(_movements(db_session, p.id)) == 1


def test_two_legitimate_receives_increment_twice(client, db_session):
    """Two genuine receipts (distinct client keys) must both apply: 1→2→3."""
    t, admin, main, p = _seed_tape(db_session, stock=1.0)
    tok = _login(client, "tape_admin")

    r1 = _restock(client, tok, p.id, 1, branch_id=main.id, movement_id="legit-a")
    assert r1.status_code == 200
    assert r1.json()["resulting_qty"] == 2.0

    r2 = _restock(client, tok, p.id, 1, branch_id=main.id, movement_id="legit-b")
    assert r2.status_code == 200
    assert r2.json()["resulting_qty"] == 3.0

    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 3.0
    assert len(_movements(db_session, p.id)) == 2


def test_ui_double_submit_same_movement_key_no_double_increment(client, db_session):
    """Simulate one user action retried with the same client_movement_id (ghost click)."""
    t, admin, main, p = _seed_tape(db_session, stock=1.0)
    tok = _login(client, "tape_admin")

    mid = "modal-session-key"
    assert _restock(client, tok, p.id, 1, branch_id=main.id, movement_id=mid).status_code == 200
    assert _restock(client, tok, p.id, 1, branch_id=main.id, movement_id=mid).status_code == 200

    assert float(_bpg(db_session, main.id, p.id).stock_qty) == 2.0
    assert len(_movements(db_session, p.id)) == 1


def test_restock_tenant_isolation(client, db_session):
    t_a, admin_a, main_a, p_a = _seed_tape(db_session, stock=1.0)
    t_b = _tenant(db_session, name="Other Shop")
    admin_b = _user(db_session, t_b.id, "other_admin", role="admin")
    main_b = _branch(db_session, t_b.id, "Main Branch", "MAIN", is_default=True)
    p_b = Product(
        name="Tape Measure B",
        barcode="TAPE-B",
        selling_price=10,
        cost_price=4,
        stock_qty=7,
        tenant_id=t_b.id,
    )
    db_session.add(p_b)
    db_session.flush()
    seed_main_branch_from_legacy(db_session, tenant_id=t_b.id, branch_id=main_b.id, product=p_b)
    sync_legacy_product_stock(db_session, p_b.id)
    db_session.commit()

    tok_a = _login(client, "tape_admin")
    # Tenant A must not be able to restock Tenant B's product.
    denied = _restock(client, tok_a, p_b.id, 1, branch_id=main_a.id)
    assert denied.status_code in (403, 404)

    assert float(_bpg(db_session, main_b.id, p_b.id).stock_qty) == 7.0
    assert _movements(db_session, p_b.id) == []

    tok_b = _login(client, "other_admin")
    ok = _restock(client, tok_b, p_b.id, 1, branch_id=main_b.id)
    assert ok.status_code == 200
    assert float(_bpg(db_session, main_b.id, p_b.id).stock_qty) == 8.0
    # Tenant A's product unchanged.
    assert float(_bpg(db_session, main_a.id, p_a.id).stock_qty) == 1.0


def test_concurrent_branch_restocks_both_apply():
    """Two simultaneous legitimate receipts on the same branch: 1+1+1 → 3, two movements."""
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
            t = Tenant(tenant_uid=str(uuid.uuid4()), name="Conc Shop")
            setup.add(t)
            setup.flush()
            main = Branch(
                tenant_id=t.id,
                name="Main",
                code="MAIN",
                is_default=True,
                is_active=True,
            )
            setup.add(main)
            setup.flush()
            p = Product(
                name="Conc Tape",
                barcode="CONC-TAPE",
                selling_price=10,
                cost_price=4,
                stock_qty=1,
                tenant_id=t.id,
            )
            setup.add(p)
            setup.flush()
            seed_main_branch_from_legacy(
                setup, tenant_id=t.id, branch_id=main.id, product=p
            )
            sync_legacy_product_stock(setup, p.id)
            setup.commit()
            product_id = p.id
            branch_id = main.id

        errors: list = []
        barrier = threading.Barrier(2)

        def _receipt(amount: float, mid: str):
            try:
                session = SessionLocal()
                try:
                    barrier.wait(timeout=5)
                    apply_product_stock_change(
                        session,
                        product_id,
                        amount,
                        "stock_received concurrent",
                        branch_id=branch_id,
                        client_movement_id=mid,
                    )
                    session.commit()
                except Exception as e:
                    session.rollback()
                    errors.append(e)
                finally:
                    session.close()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=_receipt, args=(1.0, "conc-a"))
        t2 = threading.Thread(target=_receipt, args=(1.0, "conc-b"))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert not errors, f"Concurrent restock failed: {errors}"
        with SessionLocal() as verify:
            bps = (
                verify.query(BranchProductStock)
                .filter(
                    BranchProductStock.product_id == product_id,
                    BranchProductStock.branch_id == branch_id,
                )
                .one()
            )
            assert float(bps.stock_qty) == 3.0
            movs = (
                verify.query(InventoryMovement)
                .filter(InventoryMovement.product_id == product_id)
                .all()
            )
            assert len(movs) == 2
            product = verify.query(Product).filter_by(id=product_id).one()
            assert float(product.stock_qty) == 3.0
    finally:
        Path(db_path).unlink(missing_ok=True)
        try:
            engine.dispose()
        except Exception:
            pass