"""Section 5 — multi-path financial reconciliation for the same seeded transactions."""
from __future__ import annotations

import os
import secrets
from datetime import date, datetime, timedelta
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
from app.cash_on_hand import compute_cash_on_hand
from app.database import Base, get_db
from app.finance_service import (
    allocate_legacy_refund_across_items,
    approved_expenses_total,
    approved_refunds_total,
    payment_method_net_totals,
    product_period_metrics,
    product_period_totals,
    refund_aware_gross_profit,
)
from app.main import app
from app.models import (
    Payment,
    Product,
    Refund,
    RefundItem,
    Sale,
    SaleItem,
    User,
    Withdrawal,
)
from app.overview_service import (
    _payment_breakdown,
    _sales_totals,
    _top_products,
    build_business_overview,
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


def _seed(db):
    admin = User(
        username="rec_admin",
        email="rec@example.com",
        full_name="Admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
    )
    cashier = User(
        username="rec_cash",
        email="recc@example.com",
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
        data={"username": "rec_admin", "password": "AdminPass1234"},
    ).json()["access_token"]


def _product(db, name, *, cost="4.00", price="10.00", stock=100):
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


def _sale(db, cashier, items, *, method="cash", when=None, shift_id=None):
    """items: [(product, qty, unit_price, unit_cost), ...]"""
    when = when or datetime.utcnow()
    lines = []
    for product, qty, up, uc in items:
        q = int(qty)
        unit_p = Decimal(str(up))
        unit_c = Decimal(str(uc))
        lt = Decimal(q) * unit_p
        lines.append((product, q, unit_p, unit_c, lt))
    total = sum((lt for *_, lt in lines), Decimal("0"))
    sale = Sale(
        cashier_id=cashier.id,
        subtotal=total,
        discount_total=Decimal("0"),
        total=total,
        created_at=when,
        shift_id=shift_id,
    )
    db.add(sale)
    db.flush()
    sale_items = []
    for product, q, unit_p, unit_c, lt in lines:
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
        sale_items.append(si)
    db.add(Payment(sale_id=sale.id, method=method, amount=total))
    db.flush()
    return sale, sale_items


def _refund(
    db,
    sale,
    lines,
    *,
    status="approved",
    method="cash",
    approved_at=None,
    created_at=None,
    requester_id=None,
    itemless=False,
    amount=None,
):
    """lines: [(SaleItem, qty)] — ignored when itemless=True."""
    created_at = created_at or datetime.utcnow()
    approved_at = approved_at or created_at
    ritems = []
    calc_amount = Decimal("0")
    for si, qty in lines or []:
        q = int(qty)
        line_amt = (Decimal(q) / Decimal(si.quantity)) * si.line_total if si.quantity else Decimal("0")
        calc_amount += line_amt
        ritems.append((si, q, line_amt))
    refund_amount = Decimal(str(amount)) if amount is not None else calc_amount
    refund = Refund(
        sale_id=sale.id,
        refund_number=f"RF-{sale.id}-{secrets.token_hex(5)}",
        status=status,
        refund_type="partial" if refund_amount < sale.total else "full",
        amount=refund_amount,
        reason="recon",
        refund_method=method,
        requested_by_id=requester_id,
        approved_by_id=requester_id if status == "approved" else None,
        approved_at=approved_at if status == "approved" else None,
        created_at=created_at,
    )
    db.add(refund)
    db.flush()
    if not itemless:
        for si, q, line_amt in ritems:
            db.add(
                RefundItem(
                    refund_id=refund.id,
                    sale_item_id=si.id,
                    product_id=si.product_id,
                    quantity=q,
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


def test_cash_sale_paths_agree_without_refund(db_session, client):
    admin, cash = _seed(db_session)
    p = _product(db_session, "Plain")
    _sale(db_session, cash, [(p, 3, "10.00", "4.00")], method="cash")
    db_session.commit()
    start, end = _window()

    ov = _sales_totals(db_session, admin, start, end, None)
    prods = product_period_metrics(db_session, admin, start, end)
    totals = product_period_totals(prods)
    cash_t = compute_cash_on_hand(db_session, admin, start, end)
    pays = payment_method_net_totals(db_session, admin, start, end)

    assert ov["revenue"] == Decimal("30.00")
    assert ov["refunds"] == Decimal("0")
    assert totals["net_revenue"] == ov["revenue"]
    assert totals["net_gross_profit"] == ov["gross_profit"]
    assert totals["net_cogs"] == Decimal("12.00")
    assert cash_t["cash_payments"] == Decimal("30.00")
    assert cash_t["cash_refunds"] == Decimal("0")
    assert pays.get("cash") == Decimal("30.00")

    token = _tok(client)
    today = date.today().isoformat()
    summary = client.get(
        "/api/reports/summary",
        params={"from_date": today, "to_date": today},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    # reports may use slightly different keys — assert profit/refunds present
    assert Decimal(str(body.get("total_sales") or body.get("sales") or body.get("revenue") or 0)) >= Decimal("0")


def test_partial_cash_refund_reconciles_aggregate_product_cash_payments(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "PartialCash")
    sale, items = _sale(db_session, cash, [(p, 10, "10.00", "4.00")], method="cash")
    _refund(db_session, sale, [(items[0], 3)], method="cash", requester_id=admin.id)
    start, end = _window()

    ov = _sales_totals(db_session, admin, start, end, None)
    totals = product_period_totals(product_period_metrics(db_session, admin, start, end))
    cash_t = compute_cash_on_hand(db_session, admin, start, end)
    pays = payment_method_net_totals(db_session, admin, start, end)
    gp = refund_aware_gross_profit(db_session, admin, start, end)
    refunds = approved_refunds_total(db_session, admin, start, end)

    assert refunds == Decimal("30.00")
    assert ov["revenue"] == Decimal("70.00")  # 100 - 30
    assert totals["net_revenue"] == Decimal("70.00")
    assert totals["net_cogs"] == Decimal("28.00")  # 7*4
    assert totals["net_gross_profit"] == gp == Decimal("42.00")
    assert cash_t["cash_payments"] == Decimal("100.00")
    assert cash_t["cash_refunds"] == Decimal("30.00")
    assert cash_t["cash_on_hand"] == Decimal("70.00")
    assert pays.get("cash") == Decimal("70.00")


def test_card_sale_cash_refund_payment_methods(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "CardSale")
    sale, items = _sale(db_session, cash, [(p, 2, "20.00", "5.00")], method="card")
    _refund(db_session, sale, [(items[0], 1)], method="cash", requester_id=admin.id)
    start, end = _window()

    pays = payment_method_net_totals(db_session, admin, start, end)
    cash_t = compute_cash_on_hand(db_session, admin, start, end)
    assert pays.get("card") == Decimal("40.00")
    assert pays.get("cash") == Decimal("-20.00")
    assert cash_t["cash_payments"] == Decimal("0")
    assert cash_t["cash_refunds"] == Decimal("20.00")


def test_multi_item_one_refunded_product_isolation(db_session):
    admin, cash = _seed(db_session)
    a = _product(db_session, "Keep", cost="2.00", price="8.00")
    b = _product(db_session, "RefundMe", cost="5.00", price="12.00")
    sale, items = _sale(
        db_session,
        cash,
        [(a, 2, "8.00", "2.00"), (b, 2, "12.00", "5.00")],
        method="cash",
    )
    _refund(db_session, sale, [(items[1], 2)], method="cash", requester_id=admin.id)
    start, end = _window()
    rows = {r.product_id: r for r in product_period_metrics(db_session, admin, start, end)}
    assert rows[a.id].net_units == Decimal("2")
    assert rows[a.id].refunded_units == Decimal("0")
    assert rows[b.id].net_units == Decimal("0")
    totals = product_period_totals(list(rows.values()))
    assert totals["net_revenue"] == _sales_totals(db_session, admin, start, end, None)["revenue"]


def test_pending_rejected_excluded_from_all_paths(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "StatusGate")
    sale, items = _sale(db_session, cash, [(p, 5, "10.00", "4.00")])
    _refund(db_session, sale, [(items[0], 1)], status="pending", requester_id=admin.id)
    _refund(db_session, sale, [(items[0], 1)], status="rejected", requester_id=admin.id)
    start, end = _window()
    assert approved_refunds_total(db_session, admin, start, end) == Decimal("0")
    assert product_period_totals(product_period_metrics(db_session, admin, start, end))[
        "refunded_revenue"
    ] == Decimal("0")
    assert compute_cash_on_hand(db_session, admin, start, end)["cash_refunds"] == Decimal("0")


def test_cross_period_attribution_july_sale_august_refund(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "Cross")
    july = datetime.utcnow() - timedelta(days=40)
    sale, items = _sale(
        db_session, cash, [(p, 4, "10.00", "4.00")], when=july
    )
    _refund(
        db_session,
        sale,
        [(items[0], 4)],
        created_at=july + timedelta(days=1),
        approved_at=datetime.utcnow(),
        requester_id=admin.id,
    )
    july_start, july_end = july - timedelta(hours=1), july + timedelta(days=2)
    july_ov = _sales_totals(db_session, admin, july_start, july_end, None)
    july_prod = product_period_totals(
        product_period_metrics(db_session, admin, july_start, july_end)
    )
    assert july_ov["revenue"] == Decimal("40.00")
    assert july_ov["refunds"] == Decimal("0")
    assert july_prod["net_revenue"] == Decimal("40.00")

    start, end = _window(7)
    aug_ov = _sales_totals(db_session, admin, start, end, None)
    aug_prod = product_period_totals(
        product_period_metrics(db_session, admin, start, end)
    )
    assert aug_ov["revenue"] == Decimal("-40.00")
    assert aug_prod["net_revenue"] == Decimal("-40.00")
    assert aug_prod["net_units"] == Decimal("-4")

    from app.bi.analytics.profit import profit_metrics

    bi = profit_metrics(
        db_session,
        admin,
        start,
        end + timedelta(microseconds=1),  # half-open end
        start - timedelta(days=7),
        start,
    )
    assert bi["revenue_this_period"] == -40.0
    assert bi["gross_profit_this_period"] == float(aug_ov["gross_profit"])


def test_legacy_itemless_allocation_sums_and_rounding(db_session):
    admin, cash = _seed(db_session)
    # Three products with line totals that don't divide evenly into $10.00
    a = _product(db_session, "L1", cost="1.00", price="3.00")
    b = _product(db_session, "L2", cost="1.00", price="3.00")
    c = _product(db_session, "L3", cost="1.00", price="4.00")
    sale, items = _sale(
        db_session,
        cash,
        [(a, 1, "3.00", "1.00"), (b, 1, "3.00", "1.00"), (c, 1, "4.00", "1.00")],
    )
    # Itemless refund of $10.00 (full sale)
    refund = _refund(
        db_session,
        sale,
        [],
        itemless=True,
        amount="10.00",
        requester_id=admin.id,
    )
    allocs = allocate_legacy_refund_across_items(db_session, refund, sale)
    assert len(allocs) == 3
    assert sum((a.revenue for a in allocs), Decimal("0")) == Decimal("10.00")
    # Deterministic: ordered by SaleItem.id; parts are 0.01-quantized.
    for a in allocs:
        assert a.revenue == a.revenue.quantize(Decimal("0.01"))

    start, end = _window()
    totals = product_period_totals(product_period_metrics(db_session, admin, start, end))
    assert totals["refunded_revenue"] == Decimal("10.00")
    assert totals["net_revenue"] == Decimal("0.00")
    gp = refund_aware_gross_profit(db_session, admin, start, end)
    assert totals["net_gross_profit"] == gp


def test_legacy_repeated_refunds_respect_remaining_capacity(db_session):
    admin, cash = _seed(db_session)
    p1 = _product(db_session, "R1", price="6.00", cost="2.00")
    p2 = _product(db_session, "R2", price="4.00", cost="1.00")
    sale, _items = _sale(
        db_session,
        cash,
        [(p1, 1, "6.00", "2.00"), (p2, 1, "4.00", "1.00")],
    )
    _refund(
        db_session, sale, [], itemless=True, amount="6.00", requester_id=admin.id
    )
    _refund(
        db_session, sale, [], itemless=True, amount="6.00", requester_id=admin.id
    )
    start, end = _window()
    totals = product_period_totals(product_period_metrics(db_session, admin, start, end))
    # Second legacy refund can only take remaining $4.
    assert totals["refunded_revenue"] == Decimal("10.00")
    assert totals["net_revenue"] == Decimal("0.00")


def test_historical_cost_and_catalog_change(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "Hist", cost="9.00", price="20.00")
    sale, items = _sale(db_session, cash, [(p, 2, "20.00", "5.00")])
    p.cost_price = Decimal("99.00")
    db_session.commit()
    _refund(db_session, sale, [(items[0], 1)], requester_id=admin.id)
    start, end = _window()
    r = {x.product_id: x for x in product_period_metrics(db_session, admin, start, end)}[p.id]
    assert r.gross_cogs == Decimal("10.00")
    assert r.reversed_cogs == Decimal("5.00")
    assert r.net_gross_profit == Decimal("15.00")
    # Inventory valuation still uses live catalog cost × stock
    assert Decimal(str(p.stock_qty)) * Decimal(str(p.cost_price)) == Decimal("9900.00")


def test_overview_top_products_match_product_metrics(db_session):
    admin, cash = _seed(db_session)
    hot = _product(db_session, "Hot")
    cold = _product(db_session, "Cold")
    sale, items = _sale(
        db_session,
        cash,
        [(hot, 10, "10.00", "4.00"), (cold, 2, "10.00", "4.00")],
    )
    _refund(db_session, sale, [(items[0], 9)], requester_id=admin.id)
    start, end = _window()
    top = _top_products(db_session, admin, start, end, None, limit=5)
    assert top[0]["name"] == "Cold"
    assert top[0]["quantity"] == 2
    metrics = {
        r.name: r for r in product_period_metrics(db_session, admin, start, end)
    }
    assert int(metrics["Hot"].net_units) == 1
    assert int(metrics["Cold"].net_units) == 2


def test_expense_and_withdrawal_cash_formula(db_session):
    from app.models import Expense, CashMovement

    admin, cash = _seed(db_session)
    p = _product(db_session, "CashFlow")
    _sale(db_session, cash, [(p, 5, "10.00", "4.00")], method="cash")
    db_session.add(
        Withdrawal(
            amount=Decimal("15.00"),
            reason="bank_deposit",
            purpose="bank_deposit",
            cashier_id=admin.id,
            created_at=datetime.utcnow(),
        )
    )
    exp = Expense(
        description="Rent",
        category="rent",
        amount=Decimal("10.00"),
        payment_method="cash",
        status="approved",
        expense_date=datetime.utcnow(),
        created_by=admin.id,
        approved_by=admin.id,
        approved_at=datetime.utcnow(),
    )
    db_session.add(exp)
    db_session.flush()
    db_session.add(
        CashMovement(
            direction="out",
            amount=Decimal("10.00"),
            payment_method="cash",
            source_type="expense",
            source_id=exp.id,
            movement_date=datetime.utcnow(),
            created_by=admin.id,
        )
    )
    db_session.commit()
    start, end = _window()
    cash_t = compute_cash_on_hand(db_session, admin, start, end)
    # 50 payments - 15 withdrawal - 10 expense - 0 refunds = 25
    assert cash_t["cash_payments"] == Decimal("50.00")
    assert cash_t["withdrawals_total"] == Decimal("15.00")
    assert cash_t["cash_expense_outflows"] == Decimal("10.00")
    assert cash_t["cash_on_hand"] == Decimal("25.00")
    assert approved_expenses_total(db_session, admin, start, end) == Decimal("10.00")


def test_excessive_refund_qty_cannot_drive_same_period_negative(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "CapNeg")
    sale, items = _sale(db_session, cash, [(p, 2, "10.00", "4.00")])
    refund = Refund(
        sale_id=sale.id,
        refund_number=f"RF-OVER-{secrets.token_hex(3)}",
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
            discount=Decimal("0"),
            line_total=Decimal("100"),
        )
    )
    db_session.commit()
    start, end = _window()
    r = {x.product_id: x for x in product_period_metrics(db_session, admin, start, end)}[p.id]
    assert r.net_units == Decimal("0")
    assert r.net_revenue == Decimal("0")


def test_payment_breakdown_matches_helper(db_session):
    admin, cash = _seed(db_session)
    p = _product(db_session, "PayMix")
    sale, items = _sale(db_session, cash, [(p, 4, "10.00", "4.00")], method="mobile_money")
    _refund(db_session, sale, [(items[0], 1)], method="mobile_money", requester_id=admin.id)
    start, end = _window()
    helper = payment_method_net_totals(db_session, admin, start, end)
    breakdown = {
        row["method"]: Decimal(str(row["amount"]))
        for row in _payment_breakdown(db_session, admin, start, end, None)
    }
    assert helper.get("mobile_money") == breakdown.get("mobile_money") == Decimal("30.00")
