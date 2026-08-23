"""
Section 13 — branch management, membership, switching, notifications.
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
from app.branch_models import UserBranch
from app.main import app as fastapi_app
from app.models import Product, Sale, StoreSettings, User
from app.notification_service import NotificationService
from app.quotation_models import Tenant

import app.enterprise_models  # noqa: F401
import app.branch_models  # noqa: F401


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


def _tenant(db, name="Branch Shop"):
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


def _login(client, username, password="AdminPass1234"):
    r = client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# --- Management ---


def test_owner_creates_second_branch(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own1", role="admin")
    main = _main(db_session, t.id)
    db_session.commit()
    tok = _login(client, "own1")["access_token"]
    r = client.post(
        "/api/branches",
        headers=_auth(tok),
        json={"name": "Town Branch", "code": "town"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] == "TOWN"
    assert body["inventory_rows"] == 0
    assert body["is_main"] is False
    assert db_session.query(Branch).filter(Branch.tenant_id == t.id).count() == 2
    assert db_session.query(Branch).filter(Branch.id == main.id, Branch.is_default.is_(True)).count() == 1


def test_branch_code_unique_within_tenant(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own2")
    _main(db_session, t.id)
    db_session.commit()
    tok = _login(client, "own2")["access_token"]
    assert (
        client.post(
            "/api/branches",
            headers=_auth(tok),
            json={"name": "Dup Main", "code": "MAIN"},
        ).status_code
        == 409
    )


def test_same_code_other_tenant_ok(client, db_session):
    t1 = _tenant(db_session, "S1")
    t2 = _tenant(db_session, "S2")
    _user(db_session, t1.id, "a1")
    _user(db_session, t2.id, "a2")
    _main(db_session, t1.id)
    _main(db_session, t2.id)
    db_session.commit()
    tok = _login(client, "a2")["access_token"]
    r = client.post(
        "/api/branches",
        headers=_auth(tok),
        json={"name": "West", "code": "WEST"},
    )
    assert r.status_code == 201


def test_branch_name_code_validation(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own3")
    _main(db_session, t.id)
    db_session.commit()
    tok = _login(client, "own3")["access_token"]
    assert (
        client.post("/api/branches", headers=_auth(tok), json={"name": "x"}).status_code == 400
    )
    assert (
        client.post(
            "/api/branches", headers=_auth(tok), json={"name": "Ok", "code": "bad code!"}
        ).status_code
        == 400
    )


def test_cannot_view_or_update_other_tenant_branch(client, db_session):
    t1 = _tenant(db_session, "T1")
    t2 = _tenant(db_session, "T2")
    _user(db_session, t1.id, "o_t1")
    _user(db_session, t2.id, "o_t2")
    _main(db_session, t1.id)
    b2 = _main(db_session, t2.id)
    db_session.commit()
    tok = _login(client, "o_t1")["access_token"]
    assert client.get(f"/api/branches/{b2.id}", headers=_auth(tok)).status_code == 404
    assert (
        client.patch(
            f"/api/branches/{b2.id}", headers=_auth(tok), json={"name": "Hacked"}
        ).status_code
        == 404
    )


def test_main_cannot_unsafely_deactivate(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own4")
    main = _main(db_session, t.id)
    db_session.commit()
    tok = _login(client, "own4")["access_token"]
    r = client.post(f"/api/branches/{main.id}/deactivate", headers=_auth(tok))
    assert r.status_code == 409


def test_changing_main_leaves_exactly_one(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own5")
    main = _main(db_session, t.id)
    db_session.commit()
    tok = _login(client, "own5")["access_token"]
    west = client.post(
        "/api/branches", headers=_auth(tok), json={"name": "West", "code": "WEST"}
    ).json()
    r = client.patch(
        f"/api/branches/{west['id']}",
        headers=_auth(tok),
        json={"is_main": True},
    )
    assert r.status_code == 200
    db_session.expire_all()
    mains = (
        db_session.query(Branch)
        .filter(Branch.tenant_id == t.id, Branch.is_default.is_(True))
        .all()
    )
    assert len(mains) == 1
    assert mains[0].id == west["id"]
    assert db_session.get(Branch, main.id).is_default is False


def test_creation_does_not_copy_stock(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own6")
    _main(db_session, t.id)
    db_session.add(
        Product(
            name="P",
            barcode="BC-X1",
            selling_price=1,
            cost_price=0.5,
            stock_qty=99,
            tenant_id=t.id,
        )
    )
    db_session.commit()
    tok = _login(client, "own6")["access_token"]
    body = client.post(
        "/api/branches", headers=_auth(tok), json={"name": "East", "code": "EAST"}
    ).json()
    assert body["inventory_rows"] == 0
    assert (
        db_session.query(BranchProductStock)
        .filter(BranchProductStock.branch_id == body["id"])
        .count()
        == 0
    )


def test_deactivate_preserves_history(client, db_session):
    t = _tenant(db_session)
    admin = _user(db_session, t.id, "own7")
    main = _main(db_session, t.id)
    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True, is_default=False)
    db_session.add(west)
    db_session.flush()
    db_session.add(
        Sale(
            cashier_id=admin.id,
            tenant_id=t.id,
            branch_id=west.id,
            subtotal=10,
            discount_total=0,
            total=10,
        )
    )
    db_session.commit()
    tok = _login(client, "own7")["access_token"]
    assert client.post(f"/api/branches/{west.id}/deactivate", headers=_auth(tok)).status_code == 200
    db_session.expire_all()
    assert db_session.get(Branch, west.id).is_active is False
    assert db_session.query(Sale).filter(Sale.branch_id == west.id).count() == 1


def test_branch_admin_permissions_enforced(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "cash_only", role="cashier")
    _main(db_session, t.id)
    db_session.commit()
    tok = _login(client, "cash_only")["access_token"]
    assert (
        client.post("/api/branches", headers=_auth(tok), json={"name": "Nope", "code": "NO"}).status_code
        == 403
    )


def test_invalid_branch_input_controlled_error(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "own8")
    _main(db_session, t.id)
    db_session.commit()
    tok = _login(client, "own8")["access_token"]
    r = client.get("/api/branches/not-int", headers=_auth(tok))
    assert r.status_code in (404, 422)
    assert r.status_code != 500


# --- Membership ---


def test_owner_sees_all_cashier_sees_assigned(client, db_session):
    t = _tenant(db_session)
    owner = _user(db_session, t.id, "own9")
    main = _main(db_session, t.id)
    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True)
    db_session.add(west)
    db_session.flush()
    cash = _user(db_session, t.id, "cash9", role="cashier", branch_id=main.id)
    db_session.add(
        UserBranch(
            tenant_id=t.id,
            user_id=cash.id,
            branch_id=main.id,
            role="cashier",
            is_default=True,
            is_active=True,
        )
    )
    db_session.commit()
    ot = _login(client, "own9")["access_token"]
    ct = _login(client, "cash9")["access_token"]
    owner_list = client.get("/api/branches", headers=_auth(ot)).json()
    cash_list = client.get("/api/branches", headers=_auth(ct)).json()
    assert len(owner_list) == 2
    assert len(cash_list) == 1
    assert cash_list[0]["id"] == main.id


def test_multi_membership_and_one_default(client, db_session):
    t = _tenant(db_session)
    owner = _user(db_session, t.id, "own10")
    main = _main(db_session, t.id)
    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True)
    db_session.add(west)
    db_session.flush()
    cash = _user(db_session, t.id, "cash10", role="cashier")
    db_session.commit()
    tok = _login(client, "own10")["access_token"]
    assert (
        client.post(
            f"/api/branches/{main.id}/staff",
            headers=_auth(tok),
            json={"user_id": cash.id, "role": "cashier", "is_default": True},
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/branches/{west.id}/staff",
            headers=_auth(tok),
            json={"user_id": cash.id, "role": "cashier", "is_default": True},
        ).status_code
        == 201
    )
    defaults = (
        db_session.query(UserBranch)
        .filter(
            UserBranch.user_id == cash.id,
            UserBranch.is_active.is_(True),
            UserBranch.is_default.is_(True),
        )
        .all()
    )
    assert len(defaults) == 1
    assert defaults[0].branch_id == west.id


def test_cross_tenant_and_inactive_user_assignment_rejected(client, db_session):
    t1 = _tenant(db_session, "A")
    t2 = _tenant(db_session, "B")
    owner = _user(db_session, t1.id, "own11")
    main = _main(db_session, t1.id)
    foreign = _user(db_session, t2.id, "foreign_u", role="cashier")
    inactive = _user(db_session, t1.id, "inact", role="cashier")
    inactive.is_active = False
    db_session.commit()
    tok = _login(client, "own11")["access_token"]
    assert (
        client.post(
            f"/api/branches/{main.id}/staff",
            headers=_auth(tok),
            json={"user_id": foreign.id},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/branches/{main.id}/staff",
            headers=_auth(tok),
            json={"user_id": inactive.id},
        ).status_code
        == 400
    )


# --- Switching ---


def test_switch_and_auth_me_and_consolidated(client, db_session):
    t = _tenant(db_session)
    owner = _user(db_session, t.id, "own12")
    main = _main(db_session, t.id)
    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True)
    db_session.add(west)
    db_session.flush()
    cash = _user(db_session, t.id, "cash12", role="cashier", branch_id=main.id)
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

    ot = _login(client, "own12")["access_token"]
    sw = client.post(
        "/api/branches/switch",
        headers=_auth(ot),
        json={"branchId": west.id},
    )
    assert sw.status_code == 200, sw.text
    new_tok = sw.json()["access_token"]
    me = client.get("/api/auth/me", headers=_auth(new_tok)).json()
    assert me["activeBranch"]["id"] == west.id
    assert me["branchScope"] == "branch"
    assert all(b["id"] in (main.id, west.id) for b in me["availableBranches"])

    cons = client.post(
        "/api/branches/switch",
        headers=_auth(new_tok),
        json={"scope": "all"},
    )
    assert cons.status_code == 200
    assert cons.json()["scope"] == "all"
    assert cons.json()["activeBranch"] is None

    ct = _login(client, "cash12")["access_token"]
    deny = client.post(
        "/api/branches/switch",
        headers=_auth(ct),
        json={"scope": "all"},
    )
    assert deny.status_code == 403


def test_inactive_and_unauthorized_header(client, db_session):
    from app.branch_context import resolve_branch_context
    from fastapi import HTTPException

    t = _tenant(db_session)
    owner = _user(db_session, t.id, "own13")
    main = _main(db_session, t.id)
    dead = Branch(tenant_id=t.id, name="Dead", code="DEAD", is_active=False)
    db_session.add(dead)
    db_session.flush()
    cash = _user(db_session, t.id, "cash13", role="cashier", branch_id=main.id)
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
        resolve_branch_context(db_session, cash, header_branch_id=str(dead.id))
    assert ei.value.status_code == 400

    with pytest.raises(HTTPException) as ei2:
        resolve_branch_context(db_session, cash, header_branch_id=str(99999))
    assert ei2.value.status_code in (403, 404)

    # Missing header → default membership
    ctx = resolve_branch_context(db_session, cash)
    assert ctx.branch_id == main.id


def test_legacy_user_resolves_main(client, db_session):
    from app.branch_context import resolve_branch_context

    t = _tenant(db_session)
    main = _main(db_session, t.id)
    legacy = _user(db_session, t.id, "legacy14", role="cashier")
    # no membership, no branch_id
    db_session.commit()
    ctx = resolve_branch_context(db_session, legacy)
    assert ctx.branch_id == main.id


def test_revoked_membership_invalidates_stale_token_branch(client, db_session):
    t = _tenant(db_session)
    owner = _user(db_session, t.id, "own15")
    main = _main(db_session, t.id)
    west = Branch(tenant_id=t.id, name="West", code="WEST", is_active=True)
    db_session.add(west)
    db_session.flush()
    cash = _user(db_session, t.id, "cash15", role="cashier")
    db_session.commit()
    ot = _login(client, "own15")["access_token"]
    client.post(
        f"/api/branches/{main.id}/staff",
        headers=_auth(ot),
        json={"user_id": cash.id, "is_default": True},
    )
    client.post(
        f"/api/branches/{west.id}/staff",
        headers=_auth(ot),
        json={"user_id": cash.id},
    )
    ct = _login(client, "cash15")["access_token"]
    sw = client.post(
        "/api/branches/switch",
        headers=_auth(ct),
        json={"branchId": west.id},
    )
    assert sw.status_code == 200
    west_tok = sw.json()["access_token"]
    client.delete(f"/api/branches/{west.id}/staff/{cash.id}", headers=_auth(ot))
    me = client.get("/api/auth/me", headers=_auth(west_tok)).json()
    # Stale bid should not remain as active after revoke
    assert me["activeBranch"] is None or me["activeBranch"]["id"] != west.id


def test_single_branch_login_still_works(client, db_session):
    t = _tenant(db_session)
    _user(db_session, t.id, "solo", role="admin")
    _main(db_session, t.id)
    db_session.commit()
    data = _login(client, "solo")
    assert data["access_token"]
    me = client.get("/api/auth/me", headers=_auth(data["access_token"])).json()
    assert me["activeBranch"]["code"] == "MAIN"


def test_notification_branding_tenant_scoped(db_session):
    t1 = _tenant(db_session, "StoreA")
    t2 = _tenant(db_session, "StoreB")
    db_session.add_all(
        [
            StoreSettings(
                store_name="Store A Brand",
                tenant_id=t1.id,
                default_low_stock_threshold=5,
                low_stock_email_enabled=False,
            ),
            StoreSettings(
                store_name="Store B Brand",
                tenant_id=t2.id,
                default_low_stock_threshold=50,
                low_stock_email_enabled=False,
            ),
        ]
    )
    p1 = Product(
        name="A",
        barcode="NA1",
        selling_price=1,
        cost_price=1,
        stock_qty=1,
        tenant_id=t1.id,
    )
    p2 = Product(
        name="B",
        barcode="NB1",
        selling_price=1,
        cost_price=1,
        stock_qty=1,
        tenant_id=t2.id,
    )
    db_session.add_all([p1, p2])
    db_session.commit()
    svc = NotificationService(db_session)
    assert svc.get_threshold(p1) == 5
    assert svc.get_threshold(p2) == 50
