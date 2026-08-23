"""
Section 12 — multi-branch foundation tests.

Uses in-memory SQLite. Does not touch production.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.branch_context import (
    ensure_offline_branch_id,
    list_accessible_branch_ids,
    resolve_branch_context,
    sale_branch_must_match_refund,
    user_has_branch_access,
)
from app.branch_models import UserBranch
from app.database import Base
from app.enterprise_models import Branch, BranchProductStock, StockTransfer, TRANSFER_STATUS_DISPATCHED
from app.models import (
    CashierShift,
    Expense,
    Product,
    Refund,
    Sale,
    User,
    Withdrawal,
)
from app.quotation_models import Tenant

# Ensure metadata includes branch + enterprise tables.
import app.enterprise_models  # noqa: F401
import app.branch_models  # noqa: F401


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _tenant(db, name: str = "Branch Co") -> Tenant:
    t = Tenant(tenant_uid=str(uuid.uuid4()), name=name)
    db.add(t)
    db.flush()
    return t


def _user(db, tenant_id, username: str, role: str = "cashier", **kw) -> User:
    u = User(
        username=username,
        password_hash="x",
        role=role,
        tenant_id=tenant_id,
        is_active=True,
        **kw,
    )
    db.add(u)
    db.flush()
    return u


def _branch(db, tenant_id, name: str, code: str, *, is_default: bool = False) -> Branch:
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


def test_tenant_can_create_multiple_branches(db):
    t = _tenant(db)
    a = _branch(db, t.id, "Main Branch", "MAIN", is_default=True)
    b = _branch(db, t.id, "West", "WEST")
    assert a.id != b.id
    assert db.query(Branch).filter(Branch.tenant_id == t.id).count() == 2


def test_branch_codes_unique_per_tenant(db):
    t = _tenant(db)
    _branch(db, t.id, "Main", "MAIN", is_default=True)
    db.add(Branch(tenant_id=t.id, name="Dup", code="MAIN", is_active=True))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_different_tenants_may_reuse_branch_code(db):
    t1 = _tenant(db, "A Store")
    t2 = Tenant(tenant_uid=str(uuid.uuid4()), name="B Store")
    db.add(t2)
    db.flush()
    _branch(db, t1.id, "Main", "MAIN", is_default=True)
    b2 = _branch(db, t2.id, "Main", "MAIN", is_default=True)
    assert b2.code == "MAIN"


def test_existing_tenant_receives_exactly_one_main_branch(db):
    from migrate_branches import ensure_main_branch

    t = _tenant(db)
    m1 = ensure_main_branch(db, t.id)
    m2 = ensure_main_branch(db, t.id)
    assert m1.id == m2.id
    assert db.query(Branch).filter(Branch.tenant_id == t.id, Branch.is_default.is_(True)).count() == 1


def test_migration_rerun_does_not_duplicate_branches(db):
    from migrate_branches import ensure_branch_inventory, ensure_main_branch, ensure_user_memberships

    t = _tenant(db)
    owner = _user(db, t.id, "owner1", role="admin")
    p = Product(
        name="Widget",
        barcode=f"BC-{t.id}-1",
        selling_price=10,
        cost_price=4,
        stock_qty=25,
        tenant_id=t.id,
    )
    db.add(p)
    db.flush()
    main = ensure_main_branch(db, t.id)
    ensure_user_memberships(db, t.id, main)
    ensure_branch_inventory(db, t.id, main)
    n_branches = db.query(Branch).filter(Branch.tenant_id == t.id).count()
    n_mem = db.query(UserBranch).filter(UserBranch.tenant_id == t.id).count()
    n_inv = db.query(BranchProductStock).filter(BranchProductStock.branch_id == main.id).count()
    ensure_main_branch(db, t.id)
    ensure_user_memberships(db, t.id, main)
    ensure_branch_inventory(db, t.id, main)
    assert db.query(Branch).filter(Branch.tenant_id == t.id).count() == n_branches
    assert db.query(UserBranch).filter(UserBranch.tenant_id == t.id).count() == n_mem
    assert db.query(BranchProductStock).filter(BranchProductStock.branch_id == main.id).count() == n_inv
    assert owner.branch_id == main.id


def test_owner_can_access_all_tenant_branches(db):
    t = _tenant(db)
    owner = _user(db, t.id, "own", role="admin")
    m = _branch(db, t.id, "Main", "MAIN", is_default=True)
    w = _branch(db, t.id, "West", "WEST")
    ids = list_accessible_branch_ids(db, owner)
    assert set(ids) == {m.id, w.id}
    assert user_has_branch_access(db, owner, w.id)


def test_cashier_only_assigned_branch(db):
    t = _tenant(db)
    m = _branch(db, t.id, "Main", "MAIN", is_default=True)
    w = _branch(db, t.id, "West", "WEST")
    cashier = _user(db, t.id, "c1", role="cashier", branch_id=m.id)
    db.add(
        UserBranch(
            tenant_id=t.id,
            user_id=cashier.id,
            branch_id=m.id,
            role="cashier",
            is_default=True,
            is_active=True,
        )
    )
    db.flush()
    assert user_has_branch_access(db, cashier, m.id)
    assert not user_has_branch_access(db, cashier, w.id)
    assert list_accessible_branch_ids(db, cashier) == [m.id]


def test_multi_branch_user_can_switch(db):
    t = _tenant(db)
    m = _branch(db, t.id, "Main", "MAIN", is_default=True)
    w = _branch(db, t.id, "West", "WEST")
    u = _user(db, t.id, "multi", role="supervisor")
    for bid in (m.id, w.id):
        db.add(
            UserBranch(
                tenant_id=t.id,
                user_id=u.id,
                branch_id=bid,
                role="manager",
                is_default=(bid == m.id),
                is_active=True,
            )
        )
    db.flush()
    ctx_w = resolve_branch_context(db, u, header_branch_id=str(w.id))
    assert ctx_w.branch_id == w.id
    ctx_m = resolve_branch_context(db, u, header_branch_id=str(m.id))
    assert ctx_m.branch_id == m.id


def test_user_cannot_select_other_tenant_branch(db):
    t1 = _tenant(db, "T1")
    t2 = Tenant(tenant_uid=str(uuid.uuid4()), name="T2")
    db.add(t2)
    db.flush()
    _branch(db, t1.id, "Main", "MAIN", is_default=True)
    foreign = _branch(db, t2.id, "Main", "MAIN", is_default=True)
    owner = _user(db, t1.id, "o1", role="admin")
    with pytest.raises(HTTPException) as ei:
        resolve_branch_context(db, owner, header_branch_id=str(foreign.id))
    assert ei.value.status_code in (403, 404)


def test_branch_inventory_unique_per_product_branch(db):
    t = _tenant(db)
    b = _branch(db, t.id, "Main", "MAIN", is_default=True)
    p = Product(
        name="P",
        barcode="U-1",
        selling_price=1,
        cost_price=0.5,
        stock_qty=1,
        tenant_id=t.id,
    )
    db.add(p)
    db.flush()
    db.add(BranchProductStock(tenant_id=t.id, branch_id=b.id, product_id=p.id, stock_qty=1))
    db.flush()
    db.add(BranchProductStock(tenant_id=t.id, branch_id=b.id, product_id=p.id, stock_qty=2))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_sale_and_shift_belong_to_one_branch(db):
    t = _tenant(db)
    b = _branch(db, t.id, "Main", "MAIN", is_default=True)
    cashier = _user(db, t.id, "c2", role="cashier", branch_id=b.id)
    shift = CashierShift(
        cashier_id=cashier.id,
        tenant_id=t.id,
        branch_id=b.id,
        starting_cash=0,
    )
    db.add(shift)
    db.flush()
    sale = Sale(
        cashier_id=cashier.id,
        tenant_id=t.id,
        branch_id=b.id,
        subtotal=10,
        discount_total=0,
        total=10,
        shift_id=shift.id,
    )
    db.add(sale)
    db.flush()
    assert sale.branch_id == shift.branch_id == b.id


def test_refund_inherits_sale_branch_and_rejects_mismatch(db):
    t = _tenant(db)
    b1 = _branch(db, t.id, "Main", "MAIN", is_default=True)
    b2 = _branch(db, t.id, "West", "WEST")
    cashier = _user(db, t.id, "c3", role="cashier", branch_id=b1.id)
    sale = Sale(
        cashier_id=cashier.id,
        tenant_id=t.id,
        branch_id=b1.id,
        subtotal=5,
        discount_total=0,
        total=5,
    )
    db.add(sale)
    db.flush()
    refund = Refund(
        sale_id=sale.id,
        refund_number=f"RF-{sale.id}",
        status="pending",
        refund_type="partial",
        amount=1,
        reason="test",
        refund_method="cash",
        requested_by_id=cashier.id,
        tenant_id=t.id,
        branch_id=sale.branch_id,
    )
    db.add(refund)
    db.flush()
    assert refund.branch_id == sale.branch_id
    sale_branch_must_match_refund(sale.branch_id, refund.branch_id)
    with pytest.raises(HTTPException) as ei:
        sale_branch_must_match_refund(sale.branch_id, b2.id)
    assert ei.value.status_code == 400


def test_expense_and_withdrawal_belong_to_branch(db):
    t = _tenant(db)
    b = _branch(db, t.id, "Main", "MAIN", is_default=True)
    u = _user(db, t.id, "a1", role="admin")
    ex = Expense(
        tenant_id=t.id,
        branch_id=b.id,
        category="rent",
        description="Rent",
        amount=100,
        created_by=u.id,
        status="draft",
    )
    wd = Withdrawal(
        cashier_id=u.id,
        amount=20,
        reason="float",
        tenant_id=t.id,
        branch_id=b.id,
    )
    db.add_all([ex, wd])
    db.flush()
    assert ex.branch_id == wd.branch_id == b.id


def test_invalid_branch_context_controlled_error(db):
    t = _tenant(db)
    _branch(db, t.id, "Main", "MAIN", is_default=True)
    owner = _user(db, t.id, "o2", role="admin")
    with pytest.raises(HTTPException) as ei:
        resolve_branch_context(db, owner, header_branch_id="not-an-int")
    assert ei.value.status_code == 400
    with pytest.raises(HTTPException) as ei2:
        resolve_branch_context(db, owner, header_branch_id="999999")
    assert ei2.value.status_code in (403, 404)


def test_offline_payload_requires_originating_branch():
    with pytest.raises(HTTPException) as ei:
        ensure_offline_branch_id(None)
    assert ei.value.status_code == 400
    assert ensure_offline_branch_id(7) == 7


def test_backfill_preserves_sale_totals(db):
    from migrate_branches import backfill_transaction_branch_ids, ensure_main_branch

    t = _tenant(db)
    main = ensure_main_branch(db, t.id)
    cashier = _user(db, t.id, "c4", role="cashier")
    sale = Sale(
        cashier_id=cashier.id,
        tenant_id=t.id,
        branch_id=None,
        subtotal=42.50,
        discount_total=2.50,
        total=40.00,
    )
    db.add(sale)
    db.flush()
    before = (float(sale.subtotal), float(sale.discount_total), float(sale.total))
    backfill_transaction_branch_ids(db, t.id, main)
    db.refresh(sale)
    assert sale.branch_id == main.id
    assert (float(sale.subtotal), float(sale.discount_total), float(sale.total)) == before


def test_existing_users_operate_through_main_branch(db):
    from migrate_branches import ensure_main_branch, ensure_user_memberships

    t = _tenant(db)
    cashier = _user(db, t.id, "legacy_c", role="cashier")
    assert cashier.branch_id is None
    main = ensure_main_branch(db, t.id)
    ensure_user_memberships(db, t.id, main)
    db.refresh(cashier)
    assert cashier.branch_id == main.id
    assert user_has_branch_access(db, cashier, main.id)
    ctx = resolve_branch_context(db, cashier)
    assert ctx.branch_id == main.id


def test_consolidated_analytics_do_not_double_count_transfers_design():
    assert TRANSFER_STATUS_DISPATCHED == "dispatched"
    colnames = {c.name for c in StockTransfer.__table__.columns}
    assert "from_branch_id" in colnames and "to_branch_id" in colnames
    assert "amount" not in colnames
    assert "sale_id" not in colnames
