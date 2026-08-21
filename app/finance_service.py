"""
Refund-aware profit and approved-expense aggregates.

Gross profit uses SaleItem.unit_cost when set, else live Product.cost_price.
Approved refunds reverse both revenue and COGS (via RefundItem lines when present).
Operating expenses come from approved Expense rows — never from Withdrawals.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from . import tenant_scope
from .models import Expense, Payment, Product, Refund, RefundItem, Sale, SaleItem, User


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def unit_cost_expr() -> ColumnElement:
    """Historical sold cost: coalesce(SaleItem.unit_cost, Product.cost_price).

    Do not use live Product.cost_price alone for sold-profit / COGS analytics.
    Inventory-on-hand valuation may still use catalog cost deliberately.
    """
    return func.coalesce(SaleItem.unit_cost, Product.cost_price)


def line_profit_expr() -> ColumnElement:
    return SaleItem.line_total - (SaleItem.quantity * unit_cost_expr())


def refund_effective_at_expr() -> ColumnElement:
    """Period attribution: approval date when set, else request created_at."""
    return func.coalesce(Refund.approved_at, Refund.created_at)


def _refund_in_period(start: datetime, end: datetime):
    eff = refund_effective_at_expr()
    return (eff >= start) & (eff <= end)


def approved_refunds_total(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    branch_id: Optional[int] = None,
) -> Decimal:
    """Sum of approved refund amounts attributed by effective (approval) date."""
    q = (
        db.query(func.coalesce(func.sum(Refund.amount), 0))
        .join(Sale, Refund.sale_id == Sale.id)
        .filter(
            Refund.status == "approved",
            _refund_in_period(start, end),
            tenant_scope.sale_tenant_match(user),
        )
    )
    if user.tenant_id is None:
        q = q.filter(Refund.tenant_id.is_(None))
    else:
        q = q.filter(Refund.tenant_id == user.tenant_id)
    if branch_id is not None:
        q = q.filter(Sale.branch_id == branch_id)
    return _d(q.scalar())


def sum_sale_gross_profit(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    branch_id: Optional[int] = None,
    sale_filter: Optional[Any] = None,
) -> Decimal:
    q = (
        db.query(func.coalesce(func.sum(line_profit_expr()), 0))
        .select_from(SaleItem)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .join(Product, SaleItem.product_id == Product.id)
        .filter(
            Sale.created_at >= start,
            Sale.created_at <= end,
            tenant_scope.sale_tenant_match(user),
            tenant_scope.product_tenant_match(user),
        )
    )
    if sale_filter is not None:
        q = q.filter(sale_filter)
    if branch_id is not None:
        q = q.filter(Sale.branch_id == branch_id)
    return _d(q.scalar())


def _refund_item_profit_reversal(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    branch_id: Optional[int] = None,
) -> Decimal:
    """Sum of (refund line_total − qty × cost) for approved refunds with line items."""
    cost = func.coalesce(SaleItem.unit_cost, Product.cost_price)
    q = (
        db.query(
            func.coalesce(
                func.sum(RefundItem.line_total - (RefundItem.quantity * cost)),
                0,
            )
        )
        .select_from(RefundItem)
        .join(Refund, RefundItem.refund_id == Refund.id)
        .join(Sale, Refund.sale_id == Sale.id)
        .join(SaleItem, RefundItem.sale_item_id == SaleItem.id)
        .join(Product, RefundItem.product_id == Product.id)
        .filter(
            Refund.status == "approved",
            _refund_in_period(start, end),
            tenant_scope.sale_tenant_match(user),
            tenant_scope.product_tenant_match(user),
        )
    )
    if user.tenant_id is None:
        q = q.filter(Refund.tenant_id.is_(None))
    else:
        q = q.filter(Refund.tenant_id == user.tenant_id)
    if branch_id is not None:
        q = q.filter(Sale.branch_id == branch_id)
    return _d(q.scalar())


def _refund_amount_without_items(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    branch_id: Optional[int] = None,
) -> list[tuple[Refund, Sale]]:
    """Approved refunds in range that have no RefundItem rows."""
    q = (
        db.query(Refund, Sale)
        .join(Sale, Refund.sale_id == Sale.id)
        .outerjoin(RefundItem, RefundItem.refund_id == Refund.id)
        .filter(
            Refund.status == "approved",
            _refund_in_period(start, end),
            tenant_scope.sale_tenant_match(user),
            RefundItem.id.is_(None),
        )
    )
    if user.tenant_id is None:
        q = q.filter(Refund.tenant_id.is_(None))
    else:
        q = q.filter(Refund.tenant_id == user.tenant_id)
    if branch_id is not None:
        q = q.filter(Sale.branch_id == branch_id)
    return list(q.all())


def _proportional_refund_profit(db: Session, refund: Refund, sale: Sale) -> Decimal:
    """When a refund has no line items, reverse margin via shared legacy allocator."""
    return sum(
        (a.profit for a in allocate_legacy_refund_across_items(db, refund, sale)),
        Decimal("0"),
    )


@dataclass
class LegacyLineAllocation:
    """One SaleItem's share of a legacy (itemless) approved refund."""

    sale_item_id: int
    product_id: int
    sale_item: SaleItem
    product: Product
    revenue: Decimal
    quantity: Decimal
    cogs: Decimal
    profit: Decimal


def allocate_legacy_refund_across_items(
    db: Session,
    refund: Refund,
    sale: Sale,
    *,
    remaining_rev: Optional[Dict[int, Decimal]] = None,
    remaining_qty: Optional[Dict[int, Decimal]] = None,
) -> List[LegacyLineAllocation]:
    """Pro-rate an itemless refund across the sale's lines.

    - Weights = remaining refundable line revenue (defaults to SaleItem.line_total).
    - Allocated revenues are quantized to 0.01; the last line (by SaleItem.id)
      receives the remainder so the parts sum exactly to min(refund.amount, weight_sum).
    - Quantity and COGS follow the revenue share of each line.
    - Never exceeds remaining_rev / remaining_qty per line when provided
      (supports repeated legacy refunds against the same sale).
    """
    from decimal import ROUND_HALF_UP

    sale_total = _d(sale.total)
    refund_amt = _d(refund.amount)
    if sale_total <= 0 or refund_amt <= 0:
        return []

    items = (
        db.query(SaleItem, Product)
        .join(Product, SaleItem.product_id == Product.id)
        .filter(SaleItem.sale_id == sale.id)
        .order_by(SaleItem.id.asc())
        .all()
    )
    if not items:
        return []

    weights: List[Decimal] = []
    meta: List[Tuple[SaleItem, Product, Decimal, Decimal]] = []
    for si, product in items:
        line_rev = _d(si.line_total)
        line_qty = _d(si.quantity)
        if remaining_rev is not None:
            line_rev = min(line_rev, _cap_non_negative(remaining_rev.get(si.id, line_rev)))
        if remaining_qty is not None:
            line_qty = min(line_qty, _cap_non_negative(remaining_qty.get(si.id, line_qty)))
        weights.append(line_rev)
        meta.append((si, product, line_rev, line_qty))

    weight_sum = sum(weights, Decimal("0"))
    if weight_sum <= 0:
        return []

    target = min(refund_amt, weight_sum)
    cent = Decimal("0.01")
    parts: List[Decimal] = []
    running = Decimal("0")
    for i, w in enumerate(weights):
        if i == len(weights) - 1:
            part = target - running
        else:
            part = (target * w / weight_sum).quantize(cent, rounding=ROUND_HALF_UP)
            # Keep non-negative and not past remaining target.
            if part < 0:
                part = Decimal("0")
            if running + part > target:
                part = target - running
            running += part
        parts.append(part)

    # Fix float/quantize drift: force exact sum on last line.
    drift = target - sum(parts, Decimal("0"))
    if drift != 0 and parts:
        parts[-1] = parts[-1] + drift

    out: List[LegacyLineAllocation] = []
    for (si, product, line_rev, line_qty), rev in zip(meta, parts):
        if rev <= 0 and line_rev <= 0:
            continue
        cost = _d(si.unit_cost if si.unit_cost is not None else product.cost_price)
        if line_rev > 0:
            qty = (line_qty * (rev / line_rev)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            qty = min(qty, line_qty)
        else:
            qty = Decimal("0")
        cogs = (qty * cost).quantize(cent, rounding=ROUND_HALF_UP)
        # Cap COGS so it cannot exceed full-line historical COGS share of this allocation.
        max_cogs = (line_qty * cost).quantize(cent, rounding=ROUND_HALF_UP)
        if cogs > max_cogs:
            cogs = max_cogs
        profit = rev - cogs
        out.append(
            LegacyLineAllocation(
                sale_item_id=int(si.id),
                product_id=int(product.id),
                sale_item=si,
                product=product,
                revenue=rev,
                quantity=qty,
                cogs=cogs,
                profit=profit,
            )
        )
        if remaining_rev is not None:
            remaining_rev[si.id] = _cap_non_negative(
                remaining_rev.get(si.id, _d(si.line_total)) - rev
            )
        if remaining_qty is not None:
            remaining_qty[si.id] = _cap_non_negative(
                remaining_qty.get(si.id, _d(si.quantity)) - qty
            )
    return out


def payment_method_net_totals(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    branch_id: Optional[int] = None,
    end_exclusive: bool = False,
) -> Dict[str, Decimal]:
    """Successful sale payments by method minus approved refunds by refund_method.

    Sales use Sale.created_at; refunds use coalesce(approved_at, created_at).
    """
    sale_period = _sale_created_in_period(start, end, end_exclusive=end_exclusive)
    pay_q = (
        db.query(Payment.method, func.coalesce(func.sum(Payment.amount), 0))
        .join(Sale, Payment.sale_id == Sale.id)
        .filter(sale_period, tenant_scope.sale_tenant_match(user))
        .group_by(Payment.method)
    )
    if branch_id is not None:
        pay_q = pay_q.filter(Sale.branch_id == branch_id)

    totals: Dict[str, Decimal] = {}
    for method, amt in pay_q.all():
        key = (method or "unknown").strip() or "unknown"
        totals[key] = _d(amt)

    ref_period = _refund_effective_in_period(start, end, end_exclusive=end_exclusive)
    ref_q = (
        db.query(Refund.refund_method, func.coalesce(func.sum(Refund.amount), 0))
        .join(Sale, Refund.sale_id == Sale.id)
        .filter(
            Refund.status == "approved",
            ref_period,
            tenant_scope.sale_tenant_match(user),
        )
        .group_by(Refund.refund_method)
    )
    if user.tenant_id is None:
        ref_q = ref_q.filter(Refund.tenant_id.is_(None))
    else:
        ref_q = ref_q.filter(Refund.tenant_id == user.tenant_id)
    if branch_id is not None:
        ref_q = ref_q.filter(Sale.branch_id == branch_id)

    for method, amt in ref_q.all():
        key = (method or "unknown").strip() or "unknown"
        totals[key] = totals.get(key, Decimal("0")) - _d(amt)

    return totals


def refund_gross_profit_reversal(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    branch_id: Optional[int] = None,
) -> Decimal:
    reversal = _refund_item_profit_reversal(
        db, user, start, end, branch_id=branch_id
    )
    for refund, sale in _refund_amount_without_items(
        db, user, start, end, branch_id=branch_id
    ):
        reversal += _proportional_refund_profit(db, refund, sale)
    return reversal


def refund_aware_gross_profit(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    branch_id: Optional[int] = None,
    sale_filter: Optional[Any] = None,
) -> Decimal:
    gp = sum_sale_gross_profit(
        db, user, start, end, branch_id=branch_id, sale_filter=sale_filter
    )
    return gp - refund_gross_profit_reversal(
        db, user, start, end, branch_id=branch_id
    )


def approved_expenses_total(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    branch_id: Optional[int] = None,
) -> Decimal:
    """Sum of approved operating expenses by expense_date (not withdrawals)."""
    q = tenant_scope.filter_expenses(db, user).filter(
        Expense.status == "approved",
        Expense.expense_date >= start,
        Expense.expense_date <= end,
    )
    if branch_id is not None:
        q = q.filter(
            (Expense.branch_id == branch_id) | (Expense.branch_id.is_(None))
        )
    return _d(q.with_entities(func.coalesce(func.sum(Expense.amount), 0)).scalar())


def lifetime_approved_expenses(db: Session, user: User) -> Decimal:
    q = tenant_scope.filter_expenses(db, user).filter(Expense.status == "approved")
    return _d(q.with_entities(func.coalesce(func.sum(Expense.amount), 0)).scalar())


def net_operating_profit(
    gross_profit: Decimal,
    approved_expenses: Decimal,
) -> Decimal:
    return _d(gross_profit) - _d(approved_expenses)


@dataclass
class ProductNetMetrics:
    """Refund-aware product totals for a reporting window.

    Sales attributed by ``Sale.created_at``.
    Refund reversals attributed by ``coalesce(Refund.approved_at, Refund.created_at)``.
    """

    product_id: int
    name: str = ""
    barcode: Optional[str] = None
    gross_units: Decimal = Decimal("0")
    refunded_units: Decimal = Decimal("0")
    net_units: Decimal = Decimal("0")
    gross_revenue: Decimal = Decimal("0")
    refunded_revenue: Decimal = Decimal("0")
    net_revenue: Decimal = Decimal("0")
    gross_cogs: Decimal = Decimal("0")
    reversed_cogs: Decimal = Decimal("0")
    net_cogs: Decimal = Decimal("0")
    net_gross_profit: Decimal = Decimal("0")
    sale_line_count: int = 0


def _sale_created_in_period(
    start: datetime, end: datetime, *, end_exclusive: bool
) -> Any:
    if end_exclusive:
        return (Sale.created_at >= start) & (Sale.created_at < end)
    return (Sale.created_at >= start) & (Sale.created_at <= end)


def _refund_effective_in_period(
    start: datetime, end: datetime, *, end_exclusive: bool
) -> Any:
    eff = refund_effective_at_expr()
    if end_exclusive:
        return (eff >= start) & (eff < end)
    return (eff >= start) & (eff <= end)


def _cap_non_negative(value: Decimal) -> Decimal:
    v = _d(value)
    return v if v > 0 else Decimal("0")


def product_period_metrics(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    branch_id: Optional[int] = None,
    end_exclusive: bool = False,
    active_only: bool = True,
) -> List[ProductNetMetrics]:
    """Per-product gross / refunded / net units, revenue, COGS, and GP.

    Line-level ``RefundItem`` rows drive allocation. Approved refunds with no
    line items (legacy) are pro-rated across the sale's SaleItems by line_total
    share — documented limitation, not preferred.

    Refund qty/revenue against a SaleItem are capped at that line's sold
    quantity / line_total so duplicate refund data cannot invent negative nets
    beyond a full line reversal.
    """
    by_id: Dict[int, ProductNetMetrics] = {}
    _si_ref_qty: Dict[int, Decimal] = {}
    _si_ref_rev: Dict[int, Decimal] = {}

    def _row(pid: int) -> ProductNetMetrics:
        if pid not in by_id:
            by_id[pid] = ProductNetMetrics(product_id=pid)
        return by_id[pid]

    # --- Gross from sales in period (sale date) ---
    gross_q = (
        db.query(
            Product.id,
            Product.name,
            Product.barcode,
            func.coalesce(func.sum(SaleItem.quantity), 0),
            func.coalesce(func.sum(SaleItem.line_total), 0),
            func.coalesce(func.sum(SaleItem.quantity * unit_cost_expr()), 0),
            func.count(SaleItem.id),
        )
        .select_from(SaleItem)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .join(Product, SaleItem.product_id == Product.id)
        .filter(
            _sale_created_in_period(start, end, end_exclusive=end_exclusive),
            tenant_scope.sale_tenant_match(user),
            tenant_scope.product_tenant_match(user),
        )
        .group_by(Product.id, Product.name, Product.barcode)
    )
    if active_only:
        gross_q = gross_q.filter(Product.is_active == True)  # noqa: E712
    if branch_id is not None:
        gross_q = gross_q.filter(Sale.branch_id == branch_id)

    for pid, name, barcode, qty, rev, cogs, nlines in gross_q.all():
        row = _row(int(pid))
        row.name = name or ""
        row.barcode = barcode
        row.gross_units = _d(qty)
        row.gross_revenue = _d(rev)
        row.gross_cogs = _d(cogs)
        row.sale_line_count = int(nlines or 0)

    # --- RefundItem reversals in period (approval/effective date), capped per SaleItem ---
    ri_q = (
        db.query(
            RefundItem.sale_item_id,
            RefundItem.product_id,
            Product.name,
            Product.barcode,
            SaleItem.quantity,
            SaleItem.line_total,
            SaleItem.unit_cost,
            Product.cost_price,
            func.coalesce(func.sum(RefundItem.quantity), 0),
            func.coalesce(func.sum(RefundItem.line_total), 0),
        )
        .select_from(RefundItem)
        .join(Refund, RefundItem.refund_id == Refund.id)
        .join(Sale, Refund.sale_id == Sale.id)
        .join(SaleItem, RefundItem.sale_item_id == SaleItem.id)
        .join(Product, RefundItem.product_id == Product.id)
        .filter(
            Refund.status == "approved",
            _refund_effective_in_period(start, end, end_exclusive=end_exclusive),
            tenant_scope.sale_tenant_match(user),
            tenant_scope.product_tenant_match(user),
        )
        .group_by(
            RefundItem.sale_item_id,
            RefundItem.product_id,
            Product.name,
            Product.barcode,
            SaleItem.quantity,
            SaleItem.line_total,
            SaleItem.unit_cost,
            Product.cost_price,
        )
    )
    if user.tenant_id is None:
        ri_q = ri_q.filter(Refund.tenant_id.is_(None))
    else:
        ri_q = ri_q.filter(Refund.tenant_id == user.tenant_id)
    if active_only:
        ri_q = ri_q.filter(Product.is_active == True)  # noqa: E712
    if branch_id is not None:
        ri_q = ri_q.filter(Sale.branch_id == branch_id)

    for (
        _sale_item_id,
        pid,
        name,
        barcode,
        sold_qty,
        sold_rev,
        unit_cost,
        catalog_cost,
        ref_qty,
        ref_rev,
    ) in ri_q.all():
        pid_i = int(pid)
        row = _row(pid_i)
        if not row.name:
            row.name = name or ""
            row.barcode = barcode
        sold_q = _d(sold_qty)
        sold_r = _d(sold_rev)
        raw_q = _d(ref_qty)
        raw_r = _d(ref_rev)
        rq = min(raw_q, sold_q) if sold_q > 0 else Decimal("0")
        # Cap revenue to the sale line. If refund qty covers the full line (or
        # overshoots), reverse the entire line revenue — not a partial scale of
        # an inflated refund amount.
        if sold_q > 0 and rq >= sold_q:
            rr = sold_r
        elif raw_q > 0 and sold_r > 0:
            rr = min(sold_r, raw_r * (rq / raw_q))
        else:
            rr = Decimal("0")
        cost = _d(unit_cost if unit_cost is not None else catalog_cost)
        rcogs = rq * cost
        row.refunded_units += rq
        row.refunded_revenue += rr
        row.reversed_cogs += rcogs
        # Track per-line already-reversed amounts for legacy stacking caps.
        _si_ref_qty[_sale_item_id] = _si_ref_qty.get(_sale_item_id, Decimal("0")) + rq
        _si_ref_rev[_sale_item_id] = _si_ref_rev.get(_sale_item_id, Decimal("0")) + rr

    # --- Legacy approved refunds with no RefundItem rows (shared allocator) ---
    for refund, sale in _refund_amount_without_items(
        db,
        user,
        start,
        (end - timedelta(microseconds=1)) if end_exclusive and end > start else end,
        branch_id=branch_id,
    ):
        if end_exclusive:
            eff = refund.approved_at or refund.created_at
            if eff is not None and eff >= end:
                continue
        # Remaining capacity per line after itemized refunds (and prior legacy).
        sale_items = (
            db.query(SaleItem)
            .filter(SaleItem.sale_id == sale.id)
            .all()
        )
        rem_rev = {
            si.id: _cap_non_negative(_d(si.line_total) - _si_ref_rev.get(si.id, Decimal("0")))
            for si in sale_items
        }
        rem_qty = {
            si.id: _cap_non_negative(_d(si.quantity) - _si_ref_qty.get(si.id, Decimal("0")))
            for si in sale_items
        }
        for alloc in allocate_legacy_refund_across_items(
            db, refund, sale, remaining_rev=rem_rev, remaining_qty=rem_qty
        ):
            if active_only and not alloc.product.is_active:
                continue
            row = _row(alloc.product_id)
            if not row.name:
                row.name = alloc.product.name or ""
                row.barcode = alloc.product.barcode
            row.refunded_units += alloc.quantity
            row.refunded_revenue += alloc.revenue
            row.reversed_cogs += alloc.cogs
            _si_ref_qty[alloc.sale_item_id] = (
                _si_ref_qty.get(alloc.sale_item_id, Decimal("0")) + alloc.quantity
            )
            _si_ref_rev[alloc.sale_item_id] = (
                _si_ref_rev.get(alloc.sale_item_id, Decimal("0")) + alloc.revenue
            )

    # Finalize nets. Per-SaleItem caps above prevent duplicate/excessive refund
    # data from reversing more than was sold on a line. Period nets may still be
    # negative when an approval-dated refund reverses a prior-period sale — that
    # matches aggregate P&L attribution.
    out: List[ProductNetMetrics] = []
    for row in by_id.values():
        row.net_units = row.gross_units - row.refunded_units
        row.net_revenue = row.gross_revenue - row.refunded_revenue
        row.net_cogs = row.gross_cogs - row.reversed_cogs
        # Floor only pathological float/decimal noise below a full-line reversal.
        if row.net_units < 0 and row.gross_units == 0:
            pass  # prior-period sale refunded now
        elif row.net_units < 0:
            row.net_units = Decimal("0")
            row.refunded_units = row.gross_units
        if row.net_revenue < 0 and row.gross_revenue == 0:
            pass
        elif row.net_revenue < 0:
            row.net_revenue = Decimal("0")
            row.refunded_revenue = row.gross_revenue
        if row.net_cogs < 0 and row.gross_cogs == 0:
            pass
        elif row.net_cogs < 0:
            row.net_cogs = Decimal("0")
            row.reversed_cogs = row.gross_cogs
        row.net_gross_profit = row.net_revenue - row.net_cogs
        out.append(row)
    return out


def product_period_totals(
    rows: List[ProductNetMetrics],
) -> Dict[str, Decimal]:
    """Sum product-level nets for reconciliation against aggregate finance."""
    return {
        "net_revenue": sum((r.net_revenue for r in rows), Decimal("0")),
        "net_cogs": sum((r.net_cogs for r in rows), Decimal("0")),
        "net_gross_profit": sum((r.net_gross_profit for r in rows), Decimal("0")),
        "gross_revenue": sum((r.gross_revenue for r in rows), Decimal("0")),
        "refunded_revenue": sum((r.refunded_revenue for r in rows), Decimal("0")),
        "gross_cogs": sum((r.gross_cogs for r in rows), Decimal("0")),
        "reversed_cogs": sum((r.reversed_cogs for r in rows), Decimal("0")),
        "gross_units": sum((r.gross_units for r in rows), Decimal("0")),
        "refunded_units": sum((r.refunded_units for r in rows), Decimal("0")),
        "net_units": sum((r.net_units for r in rows), Decimal("0")),
    }


def sold_cogs_net(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    branch_id: Optional[int] = None,
    end_exclusive: bool = False,
) -> Decimal:
    """Period sold COGS after approved refund COGS reversals (inventory turnover)."""
    rows = product_period_metrics(
        db,
        user,
        start,
        end,
        branch_id=branch_id,
        end_exclusive=end_exclusive,
        active_only=False,
    )
    return product_period_totals(rows)["net_cogs"]


# Expense categories (stock purchases belong in inventory/COGS, not here)
EXPENSE_CATEGORIES = (
    "rent",
    "utilities",
    "salaries_wages",
    "transport",
    "repairs_maintenance",
    "communication",
    "marketing",
    "office_supplies",
    "bank_charges",
    "other",
)

EXPENSE_CATEGORY_LABELS = {
    "rent": "Rent",
    "utilities": "Utilities",
    "salaries_wages": "Salaries / wages",
    "transport": "Transport",
    "repairs_maintenance": "Repairs and maintenance",
    "communication": "Communication",
    "marketing": "Marketing",
    "office_supplies": "Office supplies",
    "bank_charges": "Bank charges",
    "other": "Other operating costs",
}

# Map expense category → CoA account code
EXPENSE_CATEGORY_ACCOUNT = {
    "rent": "6200",
    "utilities": "6300",
    "salaries_wages": "6100",
    "transport": "6700",
    "repairs_maintenance": "6700",
    "communication": "6700",
    "marketing": "6700",
    "office_supplies": "6700",
    "bank_charges": "6700",
    "other": "6700",
}
