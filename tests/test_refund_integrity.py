"""Section 6 — refund operational integrity (controls, permissions, audit)."""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-only-jwt-secret-key-do-not-use-in-prod-64b",
)

from app import auth as auth_mod
from app.accounting_models import JournalEntry
from app.accounting_setup import initialize_chart_of_accounts
from app.cash_on_hand import compute_cash_on_hand
from app.database import Base, get_db
from app.finance_service import approved_refunds_total, payment_method_net_totals
from app.main import app
from app.models import (
    InventoryMovement,
    Payment,
    Product,
    Refund,
    RefundItem,
    Sale,
    SaleItem,
    User,
)
from app.quotation_models import Tenant
from app.refund_service import (
    PENDING_RESERVES_QUANTITY,
    RefundLineInput,
    approve_refund,
    cancel_refund,
    create_refund,
    reject_refund,
)


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

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _hash(pw: str) -> str:
    return auth_mod.get_password_hash(pw)


def _seed(db, *, prefix="ri"):
    admin = User(
        username=f"{prefix}_admin",
        email=f"{prefix}_admin@example.com",
        full_name="Admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
    )
    cashier = User(
        username=f"{prefix}_cash",
        email=f"{prefix}_cash@example.com",
        full_name="Cash",
        password_hash=_hash("CashPass1234"),
        role="cashier",
        is_active=True,
    )
    supervisor = User(
        username=f"{prefix}_sup",
        email=f"{prefix}_sup@example.com",
        full_name="Sup",
        password_hash=_hash("SupPass1234"),
        role="supervisor",
        is_active=True,
    )
    db.add_all([admin, cashier, supervisor])
    db.commit()
    for u in (admin, cashier, supervisor):
        db.refresh(u)
    return admin, cashier, supervisor


def _tok(client, username, password):
    return client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
    ).json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _product(db, name="Widget", *, stock=100, cost="4.00", price="10.00", tenant_id=None):
    p = Product(
        name=name,
        stock_qty=stock,
        cost_price=Decimal(cost),
        selling_price=Decimal(price),
        is_active=True,
        tenant_id=tenant_id,
    )
    db.add(p)
    db.flush()
    return p


def _sale(
    db,
    cashier,
    product,
    *,
    qty=5,
    unit_price="10.00",
    unit_cost="4.00",
    method="cash",
    tenant_id=None,
    total=None,
    line_total=None,
    discount_total="0",
):
    q = int(qty)
    up = Decimal(unit_price)
    uc = Decimal(unit_cost)
    lt = Decimal(str(line_total)) if line_total is not None else up * q
    sale_total = Decimal(str(total)) if total is not None else lt
    sale = Sale(
        cashier_id=cashier.id,
        subtotal=lt,
        discount_total=Decimal(str(discount_total)),
        total=sale_total,
        created_at=datetime.utcnow(),
        tenant_id=tenant_id,
    )
    db.add(sale)
    db.flush()
    si = SaleItem(
        sale_id=sale.id,
        product_id=product.id,
        quantity=q,
        unit_price=up,
        discount=Decimal("0"),
        line_total=lt,
        unit_cost=uc,
    )
    db.add(si)
    db.add(Payment(sale_id=sale.id, method=method, amount=sale_total))
    db.commit()
    db.refresh(sale)
    db.refresh(si)
    db.refresh(product)
    return sale, si


def _multi_sale(db, cashier, lines, *, method="cash", tenant_id=None):
    """lines: [(product, qty, unit_price, unit_cost), ...]"""
    built = []
    for product, qty, up, uc in lines:
        q = int(qty)
        unit_p = Decimal(str(up))
        unit_c = Decimal(str(uc))
        lt = unit_p * q
        built.append((product, q, unit_p, unit_c, lt))
    total = sum((lt for *_, lt in built), Decimal("0"))
    sale = Sale(
        cashier_id=cashier.id,
        subtotal=total,
        discount_total=Decimal("0"),
        total=total,
        created_at=datetime.utcnow(),
        tenant_id=tenant_id,
    )
    db.add(sale)
    db.flush()
    items = []
    for product, q, unit_p, unit_c, lt in built:
        si = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=q,
            unit_price=unit_p,
            discount=Decimal("0"),
            line_total=lt,
            unit_cost=unit_c,
        )
        db.add(si)
        items.append(si)
    db.add(Payment(sale_id=sale.id, method=method, amount=total))
    db.commit()
    for si in items:
        db.refresh(si)
    db.refresh(sale)
    return sale, items


def test_full_valid_refund_auto_approve(db_session, client):
    admin, cash, _ = _seed(db_session)
    p = _product(db_session, stock=10)
    sale, si = _sale(db_session, cash, p, qty=3)
    stock_before = float(p.stock_qty)
    tok = _tok(client, "ri_admin", "AdminPass1234")
    r = client.post(
        "/api/refunds",
        headers=_auth(tok),
        json={
            "sale_id": sale.id,
            "reason": "Customer return",
            "refund_method": "cash",
            "full_refund": True,
            "items": [],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert float(body["amount"]) == 30.0
    db_session.refresh(p)
    assert float(p.stock_qty) == stock_before + 3


def test_partial_valid_refund(db_session, client):
    admin, cash, _ = _seed(db_session)
    p = _product(db_session)
    sale, si = _sale(db_session, cash, p, qty=5)
    ctok = _tok(client, "ri_cash", "CashPass1234")
    r = client.post(
        "/api/refunds",
        headers=_auth(ctok),
        json={
            "sale_id": sale.id,
            "reason": "Partial return",
            "refund_method": "cash",
            "items": [{"sale_item_id": si.id, "quantity": 2}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"
    assert float(r.json()["amount"]) == 20.0
    db_session.refresh(p)
    assert float(p.stock_qty) == 100


def test_multiple_partial_refunds_within_sold_qty(db_session, client):
    admin, cash, _ = _seed(db_session)
    p = _product(db_session, stock=50)
    sale, si = _sale(db_session, cash, p, qty=5)
    tok = _tok(client, "ri_admin", "AdminPass1234")
    for qty in (2, 2, 1):
        r = client.post(
            "/api/refunds",
            headers=_auth(tok),
            json={
                "sale_id": sale.id,
                "reason": f"Part {qty}",
                "refund_method": "cash",
                "items": [{"sale_item_id": si.id, "quantity": qty}],
            },
        )
        assert r.status_code == 200, r.text
    r = client.post(
        "/api/refunds",
        headers=_auth(tok),
        json={
            "sale_id": sale.id,
            "reason": "Over",
            "refund_method": "cash",
            "items": [{"sale_item_id": si.id, "quantity": 1}],
        },
    )
    assert r.status_code == 400
    db_session.refresh(p)
    assert float(p.stock_qty) == 55


def test_qty_greater_than_sold_rejected(db_session, client):
    admin, cash, _ = _seed(db_session)
    p = _product(db_session)
    sale, si = _sale(db_session, cash, p, qty=2)
    tok = _tok(client, "ri_admin", "AdminPass1234")
    r = client.post(
        "/api/refunds",
        headers=_auth(tok),
        json={
            "sale_id": sale.id,
            "reason": "Too many",
            "refund_method": "cash",
            "items": [{"sale_item_id": si.id, "quantity": 5}],
        },
    )
    assert r.status_code == 400


def test_negative_and_zero_qty_rejected(db_session, client):
    admin, cash, _ = _seed(db_session)
    p = _product(db_session)
    sale, si = _sale(db_session, cash, p, qty=2)
    tok = _tok(client, "ri_admin", "AdminPass1234")
    for q in (0, -1):
        r = client.post(
            "/api/refunds",
            headers=_auth(tok),
            json={
                "sale_id": sale.id,
                "reason": "bad qty",
                "refund_method": "cash",
                "items": [{"sale_item_id": si.id, "quantity": q}],
            },
        )
        assert r.status_code == 422


def test_pending_does_not_reserve_but_second_approve_blocked(db_session):
    assert PENDING_RESERVES_QUANTITY is False
    admin, cash, _ = _seed(db_session, prefix="pend")
    p = _product(db_session, stock=10)
    sale, si = _sale(db_session, cash, p, qty=5)
    a = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="A",
        refund_method="cash",
        items=[RefundLineInput(si.id, 3)],
    )
    b = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="B",
        refund_method="cash",
        items=[RefundLineInput(si.id, 3)],
    )
    assert a.status == "pending" and b.status == "pending"
    approve_refund(db_session, admin, a.id)
    db_session.refresh(p)
    assert float(p.stock_qty) == 13
    with pytest.raises(Exception) as ei:
        approve_refund(db_session, admin, b.id)
    assert ei.value.status_code in (400, 409)
    db_session.refresh(p)
    assert float(p.stock_qty) == 13
    db_session.refresh(b)
    assert b.status == "pending"


def test_amount_cap_header_discount_sale(db_session):
    admin, cash, _ = _seed(db_session, prefix="disc")
    p = _product(db_session)
    sale, si = _sale(
        db_session,
        cash,
        p,
        qty=10,
        unit_price="10.00",
        total="90.00",
        line_total="100.00",
        discount_total="10.00",
    )
    with pytest.raises(Exception) as ei:
        create_refund(
            db_session,
            admin,
            sale_id=sale.id,
            reason="Full lines would exceed Sale.total",
            refund_method="cash",
            full_refund=True,
        )
    assert ei.value.status_code == 400


def test_pending_and_rejected_no_stock_or_finance(db_session, client):
    admin, cash, _ = _seed(db_session, prefix="nr")
    p = _product(db_session, stock=20)
    sale, si = _sale(db_session, cash, p, qty=4, method="cash")
    pending = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="wait",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    db_session.refresh(p)
    assert float(p.stock_qty) == 20
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.utcnow().replace(hour=23, minute=59, second=59, microsecond=999999)
    assert approved_refunds_total(db_session, admin, start, end) == Decimal("0")
    cash_t = compute_cash_on_hand(db_session, admin, start, end)
    assert cash_t["cash_refunds"] == Decimal("0")

    reject_refund(db_session, admin, pending.id, "nope")
    db_session.refresh(p)
    assert float(p.stock_qty) == 20
    assert approved_refunds_total(db_session, admin, start, end) == Decimal("0")


def test_approved_restores_exact_qty_once(db_session):
    admin, cash, _ = _seed(db_session, prefix="stk")
    initialize_chart_of_accounts(db_session)
    p = _product(db_session, stock=7)
    sale, si = _sale(db_session, cash, p, qty=4)
    refund = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="restore",
        refund_method="cash",
        items=[RefundLineInput(si.id, 2)],
    )
    approve_refund(db_session, admin, refund.id)
    db_session.refresh(p)
    assert float(p.stock_qty) == 9
    moves = (
        db_session.query(InventoryMovement)
        .filter(InventoryMovement.reason == f"Refund {refund.refund_number}")
        .all()
    )
    assert len(moves) == 1
    assert float(moves[0].change_qty) == 2.0


def test_approved_status_persists_after_reload_new_session(db_session):
    """Section 7 regression: approve → commit → new session still shows APPROVED.

    Guards the Section 6 bug where refresh wiped approved status before commit.
    """
    admin, cash, _ = _seed(db_session, prefix="persist")
    initialize_chart_of_accounts(db_session)
    p = _product(db_session, stock=10)
    sale, si = _sale(db_session, cash, p, qty=3, method="cash")
    refund = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="persist status",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    assert refund.status == "pending"
    approve_refund(db_session, admin, refund.id)
    rid = refund.id
    approved_at = refund.approved_at
    approved_by = refund.approved_by_id
    assert refund.status == "approved"
    assert approved_by == admin.id
    assert approved_at is not None

    # New session/query — must not appear pending
    bind = db_session.get_bind()
    Session = sessionmaker(bind=bind, autoflush=False, autocommit=False, future=True)
    db2 = Session()
    try:
        reloaded = db2.query(Refund).filter(Refund.id == rid).one()
        assert reloaded.status == "approved"
        assert reloaded.approved_by_id == approved_by
        assert reloaded.approved_at == approved_at
        assert db2.query(Refund).filter(Refund.id == rid, Refund.status == "pending").count() == 0
        stock = db2.query(Product).filter(Product.id == p.id).one().stock_qty
        assert float(stock) == 11.0
        moves = (
            db2.query(InventoryMovement)
            .filter(InventoryMovement.reason == f"Refund {reloaded.refund_number}")
            .count()
        )
        assert moves == 1
        je = (
            db2.query(JournalEntry)
            .filter(
                JournalEntry.reference_type == "REFUND",
                JournalEntry.reference_id == rid,
            )
            .count()
        )
        assert je == 1
    finally:
        db2.close()


def test_duplicate_approval_conflict_no_double_effects(db_session):
    admin, cash, _ = _seed(db_session, prefix="dup")
    initialize_chart_of_accounts(db_session)
    p = _product(db_session, stock=10)
    sale, si = _sale(db_session, cash, p, qty=3, method="cash")
    refund = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="once",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    approve_refund(db_session, admin, refund.id)
    db_session.refresh(p)
    stock_after = float(p.stock_qty)
    approved_at = refund.approved_at
    je_count = (
        db_session.query(func.count(JournalEntry.id))
        .filter(
            JournalEntry.reference_type == "REFUND",
            JournalEntry.reference_id == refund.id,
        )
        .scalar()
    )
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.utcnow().replace(hour=23, minute=59, second=59, microsecond=999999)
    cash_once = compute_cash_on_hand(db_session, admin, start, end)["cash_refunds"]

    with pytest.raises(Exception) as ei:
        approve_refund(db_session, admin, refund.id)
    assert ei.value.status_code == 409

    db_session.refresh(p)
    db_session.refresh(refund)
    assert float(p.stock_qty) == stock_after
    assert refund.approved_at == approved_at
    je_count2 = (
        db_session.query(func.count(JournalEntry.id))
        .filter(
            JournalEntry.reference_type == "REFUND",
            JournalEntry.reference_id == refund.id,
        )
        .scalar()
    )
    assert je_count2 == je_count == 1
    assert (
        compute_cash_on_hand(db_session, admin, start, end)["cash_refunds"] == cash_once
    )


def test_invalid_transitions(db_session):
    admin, cash, _ = _seed(db_session, prefix="tr")
    p = _product(db_session)
    sale, si = _sale(db_session, cash, p, qty=2)
    refund = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="x",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    reject_refund(db_session, admin, refund.id, "no")
    with pytest.raises(Exception) as ei:
        approve_refund(db_session, admin, refund.id)
    assert ei.value.status_code == 409

    refund2 = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="y",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    cancel_refund(db_session, cash, refund2.id)
    db_session.refresh(refund2)
    assert refund2.status == "cancelled"
    with pytest.raises(Exception) as ei:
        approve_refund(db_session, admin, refund2.id)
    assert ei.value.status_code == 409


def test_approval_failure_rolls_back(db_session):
    admin, cash, _ = _seed(db_session, prefix="rb")
    initialize_chart_of_accounts(db_session)
    p = _product(db_session, stock=10)
    sale, si = _sale(db_session, cash, p, qty=2)
    refund = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="fail",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    with patch(
        "app.refund_service.AccountingEngine.post_refund",
        side_effect=RuntimeError("gl boom"),
    ):
        with pytest.raises(Exception):
            approve_refund(db_session, admin, refund.id)
    db_session.refresh(refund)
    db_session.refresh(p)
    assert refund.status == "pending"
    assert float(p.stock_qty) == 10
    assert (
        db_session.query(InventoryMovement)
        .filter(InventoryMovement.reason.like("Refund %"))
        .count()
        == 0
    )


def test_cross_tenant_refund_blocked(db_session, client):
    t1 = Tenant(tenant_uid="ri-t1", name="A")
    t2 = Tenant(tenant_uid="ri-t2", name="B")
    db_session.add_all([t1, t2])
    db_session.flush()
    admin_a = User(
        username="ri_a",
        email="a@ex.com",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
        tenant_id=t1.id,
        full_name="A",
    )
    admin_b = User(
        username="ri_b",
        email="b@ex.com",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
        tenant_id=t2.id,
        full_name="B",
    )
    cash_b = User(
        username="ri_bc",
        email="bc@ex.com",
        password_hash=_hash("CashPass1234"),
        role="cashier",
        is_active=True,
        tenant_id=t2.id,
        full_name="BC",
    )
    db_session.add_all([admin_a, admin_b, cash_b])
    db_session.commit()
    p = _product(db_session, tenant_id=t2.id)
    sale, si = _sale(db_session, cash_b, p, qty=2, tenant_id=t2.id)

    tok_a = _tok(client, "ri_a", "AdminPass1234")
    r = client.post(
        "/api/refunds",
        headers=_auth(tok_a),
        json={
            "sale_id": sale.id,
            "reason": "cross",
            "refund_method": "cash",
            "items": [{"sale_item_id": si.id, "quantity": 1}],
        },
    )
    assert r.status_code == 404

    pending = create_refund(
        db_session,
        cash_b,
        sale_id=sale.id,
        reason="b pending",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    r = client.post(
        f"/api/refunds/{pending.id}/approve",
        headers=_auth(tok_a),
    )
    assert r.status_code in (403, 404)

    r = client.get(f"/api/refunds/{pending.id}", headers=_auth(tok_a))
    assert r.status_code in (403, 404)


def test_cashier_cannot_approve(db_session, client):
    admin, cash, _ = _seed(db_session, prefix="perm")
    p = _product(db_session)
    sale, si = _sale(db_session, cash, p, qty=2)
    pending = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="need approval",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    ctok = _tok(client, "perm_cash", "CashPass1234")
    r = client.post(
        f"/api/refunds/{pending.id}/approve",
        headers=_auth(ctok),
    )
    assert r.status_code == 403


def test_authorized_supervisor_can_approve(db_session, client):
    admin, cash, sup = _seed(db_session, prefix="ok")
    p = _product(db_session, stock=5)
    sale, si = _sale(db_session, cash, p, qty=2)
    pending = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="ok",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    stok = _tok(client, "ok_sup", "SupPass1234")
    r = client.post(
        f"/api/refunds/{pending.id}/approve",
        headers=_auth(stok),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["approved_by_id"] == sup.id


def test_client_cannot_manipulate_price_or_tenant(db_session, client):
    admin, cash, _ = _seed(db_session, prefix="trust")
    p = _product(db_session)
    sale, si = _sale(db_session, cash, p, qty=2, unit_price="10.00")
    tok = _tok(client, "trust_admin", "AdminPass1234")
    r = client.post(
        "/api/refunds",
        headers=_auth(tok),
        json={
            "sale_id": sale.id,
            "reason": "price attack",
            "refund_method": "cash",
            "amount": 9999,
            "unit_price": 999,
            "line_total": 9999,
            "tenant_id": 999,
            "store_id": 999,
            "items": [
                {
                    "sale_item_id": si.id,
                    "quantity": 1,
                    "unit_price": 999,
                    "line_total": 9999,
                    "cost_price": 0,
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert float(r.json()["amount"]) == 10.0
    assert r.json().get("tenant_id") in (None, admin.tenant_id)


def test_multi_item_restores_only_selected(db_session):
    admin, cash, _ = _seed(db_session, prefix="mi")
    a = _product(db_session, "A", stock=10)
    b = _product(db_session, "B", stock=10)
    sale, items = _multi_sale(
        db_session,
        cash,
        [(a, 3, "10", "4"), (b, 3, "20", "5")],
    )
    create_refund(
        db_session,
        admin,
        sale_id=sale.id,
        reason="only A",
        refund_method="cash",
        items=[RefundLineInput(items[0].id, 2)],
    )
    db_session.refresh(a)
    db_session.refresh(b)
    assert float(a.stock_qty) == 12
    assert float(b.stock_qty) == 10


def test_cash_and_card_method_effects_once(db_session):
    admin, cash, _ = _seed(db_session, prefix="pay")
    p = _product(db_session, stock=10)
    sale, si = _sale(db_session, cash, p, qty=2, method="card", unit_price="25.00")
    create_refund(
        db_session,
        admin,
        sale_id=sale.id,
        reason="card refund",
        refund_method="card",
        items=[RefundLineInput(si.id, 1)],
    )
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.utcnow().replace(hour=23, minute=59, second=59, microsecond=999999)
    pays = payment_method_net_totals(db_session, admin, start, end)
    assert pays.get("card") == Decimal("25.00")
    cash_t = compute_cash_on_hand(db_session, admin, start, end)
    assert cash_t["cash_refunds"] == Decimal("0")


def test_audit_actors_retained(db_session):
    admin, cash, _ = _seed(db_session, prefix="aud")
    p = _product(db_session)
    sale, si = _sale(db_session, cash, p, qty=2)
    refund = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="keep reason",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    assert refund.requested_by_id == cash.id
    assert refund.reason == "keep reason"
    approve_refund(db_session, admin, refund.id)
    db_session.refresh(refund)
    assert refund.requested_by_id == cash.id
    assert refund.approved_by_id == admin.id
    assert refund.approved_at is not None
    assert refund.reason == "keep reason"
    first_approved_at = refund.approved_at
    with pytest.raises(Exception):
        approve_refund(db_session, admin, refund.id)
    db_session.refresh(refund)
    assert refund.approved_at == first_approved_at


def test_legacy_itemless_immutable(db_session):
    admin, cash, _ = _seed(db_session, prefix="leg")
    p = _product(db_session)
    sale, si = _sale(db_session, cash, p, qty=2)
    legacy = Refund(
        sale_id=sale.id,
        refund_number="RF-LEGACY-1",
        status="pending",
        refund_type="partial",
        amount=Decimal("10"),
        reason="legacy",
        refund_method="cash",
        requested_by_id=cash.id,
        tenant_id=None,
    )
    db_session.add(legacy)
    db_session.commit()
    with pytest.raises(Exception) as ei:
        approve_refund(db_session, admin, legacy.id)
    assert ei.value.status_code == 409
    legacy.status = "approved"
    legacy.approved_at = datetime.utcnow()
    legacy.approved_by_id = admin.id
    db_session.commit()
    row = db_session.query(Refund).filter_by(id=legacy.id).one()
    assert row.status == "approved"
    assert db_session.query(RefundItem).filter_by(refund_id=legacy.id).count() == 0


def test_inactive_user_cannot_approve(db_session, client):
    admin, cash, _ = _seed(db_session, prefix="ina")
    p = _product(db_session)
    sale, si = _sale(db_session, cash, p, qty=1)
    pending = create_refund(
        db_session,
        cash,
        sale_id=sale.id,
        reason="x",
        refund_method="cash",
        items=[RefundLineInput(si.id, 1)],
    )
    admin.is_active = False
    db_session.commit()
    r = client.post(
        "/api/auth/token",
        data={"username": "ina_admin", "password": "AdminPass1234"},
    )
    if r.status_code == 200:
        tok = r.json()["access_token"]
        ar = client.post(
            f"/api/refunds/{pending.id}/approve",
            headers=_auth(tok),
        )
        assert ar.status_code in (401, 403)
    else:
        assert r.status_code in (401, 403)
