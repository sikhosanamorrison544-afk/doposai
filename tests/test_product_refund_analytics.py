"""Section 4 — product-level refund-aware analytics (SaleItem / RefundItem)."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
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
from app.finance_service import (
    approved_refunds_total,
    product_period_metrics,
    product_period_totals,
    refund_aware_gross_profit,
    sum_sale_gross_profit,
)
from app.main import app
from app.models import Payment, Product, Refund, RefundItem, Sale, SaleItem, User


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


def _seed(db):
    admin = User(
        username="pra_admin",
        email="pra@example.com",
        full_name="Admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
    )
    cashier = User(
        username="pra_cash",
        email="prac@example.com",
        full_name="Cash",
        password_hash=_hash("CashPass1234"),
        role="cashier",
        is_active=True,
    )
    db.add_all([admin, cashier])
    db.commit()
    db.refresh(admin)
    db.refresh(cashier)
    return admin, cashier


def _tok(client):
    return client.post(
        "/api/auth/token",
        data={"username": "pra_admin", "password": "AdminPass1234"},
    ).json()["access_token"]


def _product(db, name, *, stock=100, cost="5.00", price="10.00"):
    p = Product(
        name=name,
        stock_qty=stock,
        cost_price=Decimal(cost),
        selling_price=Decimal(price),
        is_active=True,
    )
    db.add(p)
    db.flush()
    return p


def _sale_with_items(db, cashier, items, *, when=None):
    """items: list of (product, qty, unit_price, unit_cost)."""
    when = when or datetime.utcnow()
    lines = []
    for product, qty, unit_price, unit_cost in items:
        q = int(qty)
        up = Decimal(str(unit_price))
        uc = Decimal(str(unit_cost))
        lt = Decimal(q) * up
        lines.append((product, q, up, uc, lt))
    total = sum((lt for *_, lt in lines), Decimal("0"))
    sale = Sale(
        cashier_id=cashier.id,
        subtotal=total,
        discount_total=Decimal("0"),
        total=total,
        created_at=when,
    )
    db.add(sale)
    db.flush()
    sale_items = []
    for product, qty, unit_price, unit_cost, lt in lines:
        si = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=qty,
            unit_price=unit_price,
            discount=Decimal("0"),
            line_total=lt,
            unit_cost=unit_cost,
        )
        db.add(si)
        sale_items.append(si)
    db.add(
        Payment(
            sale_id=sale.id,
            method="cash",
            amount=total,
        )
    )
    db.flush()
    return sale, sale_items


def _approve_refund(
    db,
    sale,
    sale_items_qty,
    *,
    status="approved",
    approved_at=None,
    created_at=None,
    requester_id=None,
):
    """sale_items_qty: list of (SaleItem, qty_to_refund)."""
    import secrets

    created_at = created_at or datetime.utcnow()
    approved_at = approved_at or created_at
    amount = Decimal("0")
    ritems = []
    for si, qty in sale_items_qty:
        qty = int(qty)
        line_amt = (Decimal(qty) / Decimal(si.quantity)) * si.line_total if si.quantity else Decimal("0")
        amount += line_amt
        ritems.append((si, qty, line_amt))
    refund = Refund(
        sale_id=sale.id,
        refund_number=f"RF-{sale.id}-{secrets.token_hex(6)}",
        status=status,
        refund_type="partial" if amount < sale.total else "full",
        amount=amount,
        reason="test",
        refund_method="cash",
        requested_by_id=requester_id,
        approved_by_id=requester_id if status == "approved" else None,
        approved_at=approved_at if status == "approved" else None,
        created_at=created_at,
    )
    db.add(refund)
    db.flush()
    for si, qty, line_amt in ritems:
        db.add(
            RefundItem(
                refund_id=refund.id,
                sale_item_id=si.id,
                product_id=si.product_id,
                quantity=qty,
                unit_price=si.unit_price,
                discount=Decimal("0"),
                line_total=line_amt,
            )
        )
    db.commit()
    db.refresh(refund)
    return refund


def _window(days=30):
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    return start, end


def test_full_refund_one_product(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "Widget")
    sale, items = _sale_with_items(
        db_session, cash, [(p, 2, "10.00", "4.00")]
    )
    _approve_refund(db_session, sale, [(items[0], 2)], requester_id=admin.id)
    start, end = _window()
    rows = {r.product_id: r for r in product_period_metrics(db_session, admin, start, end)}
    r = rows[p.id]
    assert r.gross_units == Decimal("2")
    assert r.refunded_units == Decimal("2")
    assert r.net_units == Decimal("0")
    assert r.net_revenue == Decimal("0")
    assert r.net_cogs == Decimal("0")
    assert r.net_gross_profit == Decimal("0")


def test_partial_quantity_refund(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "Partial")
    sale, items = _sale_with_items(
        db_session, cash, [(p, 10, "10.00", "3.00")]
    )
    _approve_refund(db_session, sale, [(items[0], 3)], requester_id=admin.id)
    start, end = _window()
    r = {x.product_id: x for x in product_period_metrics(db_session, admin, start, end)}[p.id]
    assert r.gross_units == Decimal("10")
    assert r.refunded_units == Decimal("3")
    assert r.net_units == Decimal("7")
    assert r.net_revenue == Decimal("70.00")
    assert r.net_cogs == Decimal("21.00")  # 7 * 3
    assert r.net_gross_profit == Decimal("49.00")


def test_partial_value_refund(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "Value")
    sale, items = _sale_with_items(
        db_session, cash, [(p, 4, "25.00", "10.00")]
    )
    # Refund 1 unit ($25) — partial value of the sale
    _approve_refund(db_session, sale, [(items[0], 1)], requester_id=admin.id)
    start, end = _window()
    r = {x.product_id: x for x in product_period_metrics(db_session, admin, start, end)}[p.id]
    assert r.net_units == Decimal("3")
    assert r.net_revenue == Decimal("75.00")
    assert r.refunded_revenue == Decimal("25.00")


def test_one_refunded_item_in_multi_item_sale(db_session):
    admin, cash = _seed(db_session)
    a = _product(db_session, "Alpha", cost="2.00", price="8.00")
    b = _product(db_session, "Beta", cost="5.00", price="12.00")
    sale, items = _sale_with_items(
        db_session,
        cash,
        [(a, 2, "8.00", "2.00"), (b, 3, "12.00", "5.00")],
    )
    _approve_refund(db_session, sale, [(items[0], 2)], requester_id=admin.id)
    start, end = _window()
    rows = {r.product_id: r for r in product_period_metrics(db_session, admin, start, end)}
    assert rows[a.id].net_units == Decimal("0")
    assert rows[a.id].net_revenue == Decimal("0")
    assert rows[b.id].net_units == Decimal("3")
    assert rows[b.id].net_revenue == Decimal("36.00")
    assert rows[b.id].refunded_units == Decimal("0")


def test_multiple_products_refunded_separately(db_session):
    admin, cash = _seed(db_session)
    a = _product(db_session, "A1")
    b = _product(db_session, "B1")
    sale, items = _sale_with_items(
        db_session, cash, [(a, 5, "10.00", "4.00"), (b, 5, "10.00", "4.00")]
    )
    _approve_refund(db_session, sale, [(items[0], 1)], requester_id=admin.id)
    _approve_refund(db_session, sale, [(items[1], 2)], requester_id=admin.id)
    start, end = _window()
    rows = {r.product_id: r for r in product_period_metrics(db_session, admin, start, end)}
    assert rows[a.id].net_units == Decimal("4")
    assert rows[b.id].net_units == Decimal("3")


def test_multiple_approved_refunds_same_sale_item(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "MultiRef")
    sale, items = _sale_with_items(
        db_session, cash, [(p, 10, "10.00", "4.00")]
    )
    _approve_refund(db_session, sale, [(items[0], 2)], requester_id=admin.id)
    _approve_refund(db_session, sale, [(items[0], 3)], requester_id=admin.id)
    start, end = _window()
    r = {x.product_id: x for x in product_period_metrics(db_session, admin, start, end)}[p.id]
    assert r.refunded_units == Decimal("5")
    assert r.net_units == Decimal("5")


def test_pending_and_rejected_refunds_excluded(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "Status")
    sale, items = _sale_with_items(
        db_session, cash, [(p, 10, "10.00", "4.00")]
    )
    _approve_refund(
        db_session, sale, [(items[0], 2)], status="pending", requester_id=admin.id
    )
    _approve_refund(
        db_session, sale, [(items[0], 3)], status="rejected", requester_id=admin.id
    )
    start, end = _window()
    r = {x.product_id: x for x in product_period_metrics(db_session, admin, start, end)}[p.id]
    assert r.refunded_units == Decimal("0")
    assert r.net_units == Decimal("10")


def test_historical_unit_cost_not_live_catalog(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "HistCost", cost="9.00", price="20.00")
    sale, items = _sale_with_items(
        db_session, cash, [(p, 2, "20.00", "5.00")]  # snapshotted cost 5
    )
    p.cost_price = Decimal("99.00")  # catalog changes after sale
    db_session.commit()
    _approve_refund(db_session, sale, [(items[0], 1)], requester_id=admin.id)
    start, end = _window()
    r = {x.product_id: x for x in product_period_metrics(db_session, admin, start, end)}[p.id]
    assert r.gross_cogs == Decimal("10.00")  # 2 * 5
    assert r.reversed_cogs == Decimal("5.00")  # 1 * 5
    assert r.net_cogs == Decimal("5.00")
    assert r.net_gross_profit == Decimal("15.00")  # 20 - 5


def test_missing_unit_cost_falls_back_to_product_cost(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "Fallback", cost="6.00", price="15.00")
    sale = Sale(
        cashier_id=cash.id,
        subtotal=Decimal("15"),
        discount_total=0,
        total=Decimal("15"),
        created_at=datetime.utcnow(),
    )
    db_session.add(sale)
    db_session.flush()
    si = SaleItem(
        sale_id=sale.id,
        product_id=p.id,
        quantity=1,
        unit_price=Decimal("15"),
        discount=0,
        line_total=Decimal("15"),
        unit_cost=None,
    )
    db_session.add(si)
    db_session.commit()
    start, end = _window()
    r = {x.product_id: x for x in product_period_metrics(db_session, admin, start, end)}[p.id]
    assert r.gross_cogs == Decimal("6.00")
    assert r.net_gross_profit == Decimal("9.00")


def test_approval_date_different_period(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "CrossPeriod")
    july = datetime.utcnow() - timedelta(days=45)
    sale, items = _sale_with_items(
        db_session, cash, [(p, 4, "10.00", "4.00")], when=july
    )
    # Refund approved today
    _approve_refund(
        db_session,
        sale,
        [(items[0], 4)],
        created_at=july + timedelta(days=1),
        approved_at=datetime.utcnow(),
        requester_id=admin.id,
    )
    # July window: full gross, no refund
    july_start = july - timedelta(days=1)
    july_end = july + timedelta(days=2)
    july_rows = product_period_metrics(db_session, admin, july_start, july_end)
    jr = {r.product_id: r for r in july_rows}[p.id]
    assert jr.gross_units == Decimal("4")
    assert jr.refunded_units == Decimal("0")
    assert jr.net_units == Decimal("4")

    # Recent window: no gross sale, full refund reversal
    start, end = _window(7)
    aug_rows = {r.product_id: r for r in product_period_metrics(db_session, admin, start, end)}
    ar = aug_rows[p.id]
    assert ar.gross_units == Decimal("0")
    assert ar.refunded_units == Decimal("4")
    assert ar.net_units == Decimal("-4")
    assert ar.net_revenue == Decimal("-40.00")


def test_excessive_refund_qty_capped(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "Cap")
    sale, items = _sale_with_items(
        db_session, cash, [(p, 2, "10.00", "4.00")]
    )
    # Fabricate over-refund qty on the line
    refund = Refund(
        sale_id=sale.id,
        refund_number="RF-OVER",
        status="approved",
        refund_type="partial",
        amount=Decimal("100"),
        reason="bad",
        refund_method="cash",
        requested_by_id=admin.id,
        approved_by_id=admin.id,
        approved_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
    )
    db_session.add(refund)
    db_session.flush()
    db_session.add(
        RefundItem(
            refund_id=refund.id,
            sale_item_id=items[0].id,
            product_id=p.id,
            quantity=99,
            unit_price=Decimal("10"),
            discount=0,
            line_total=Decimal("100"),
        )
    )
    db_session.commit()
    start, end = _window()
    r = {x.product_id: x for x in product_period_metrics(db_session, admin, start, end)}[p.id]
    assert r.refunded_units == Decimal("2")  # capped
    assert r.net_units == Decimal("0")
    assert r.net_revenue == Decimal("0")


def test_top_and_least_selling_change_after_refund(client, db_session):
    admin, cash = _seed(db_session)
    hot = _product(db_session, "HotSeller")
    cold = _product(db_session, "ColdSeller")
    sale, items = _sale_with_items(
        db_session,
        cash,
        [(hot, 20, "10.00", "4.00"), (cold, 5, "10.00", "4.00")],
    )
    token = _tok(client)
    top = client.get(
        "/api/analytics/top-selling?days=30",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert top.status_code == 200
    assert top.json()["product_name"] == "HotSeller"
    least = client.get(
        "/api/analytics/least-selling?days=30",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert least.status_code == 200
    assert least.json()["product_name"] == "ColdSeller"

    # Fully refund the hot seller → cold becomes top by net qty
    _approve_refund(db_session, sale, [(items[0], 20)], requester_id=admin.id)
    top2 = client.get(
        "/api/analytics/top-selling?days=30",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert top2["product_name"] == "ColdSeller"
    assert top2["total_quantity_sold"] == 5


def test_product_totals_reconcile_with_aggregate(db_session):
    admin, cash = _seed(db_session)
    a = _product(db_session, "RecA", cost="3.00", price="10.00")
    b = _product(db_session, "RecB", cost="4.00", price="12.00")
    sale, items = _sale_with_items(
        db_session,
        cash,
        [(a, 4, "10.00", "3.00"), (b, 2, "12.00", "4.00")],
    )
    _approve_refund(db_session, sale, [(items[0], 1), (items[1], 1)], requester_id=admin.id)
    start, end = _window()
    rows = product_period_metrics(db_session, admin, start, end)
    totals = product_period_totals(rows)

    refunds = approved_refunds_total(db_session, admin, start, end)
    gross_rev = sum((r.gross_revenue for r in rows), Decimal("0"))
    assert totals["refunded_revenue"] == refunds
    assert totals["net_revenue"] == gross_rev - refunds

    agg_gp = refund_aware_gross_profit(db_session, admin, start, end)
    assert totals["net_gross_profit"] == agg_gp

    # COGS: gross from sales − reversed on refund lines
    assert totals["net_cogs"] == totals["gross_cogs"] - totals["reversed_cogs"]


def test_stock_valuation_unaffected_by_refund_analytics(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "StockVal", stock=50, cost="7.50", price="15.00")
    sale, items = _sale_with_items(
        db_session, cash, [(p, 5, "15.00", "7.50")]
    )
    # Analytics refund does not mutate stock in this helper path
    before = float(p.stock_qty)
    cost = Decimal(str(p.cost_price))
    _approve_refund(db_session, sale, [(items[0], 2)], requester_id=admin.id)
    db_session.refresh(p)
    assert float(p.stock_qty) == before
    assert Decimal(str(p.cost_price)) == cost
    inv_value = Decimal(str(p.stock_qty)) * Decimal(str(p.cost_price))
    assert inv_value == Decimal("375.00")


def test_overview_top_products_net_quantity(db_session):
    from app.overview_service import _top_products

    admin, cash = _seed(db_session)
    p = _product(db_session, "OvTop")
    sale, items = _sale_with_items(
        db_session, cash, [(p, 8, "10.00", "4.00")]
    )
    _approve_refund(db_session, sale, [(items[0], 3)], requester_id=admin.id)
    start, end = _window()
    top = _top_products(db_session, admin, start, end, None, limit=5)
    assert top[0]["name"] == "OvTop"
    assert top[0]["quantity"] == 5
    assert top[0]["revenue"] == 50.0
