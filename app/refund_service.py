"""Refund request, approval, stock reversal, and accounting."""
from __future__ import annotations

import logging
import random
import string
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import tenant_scope
from .accounting_engine import AccountingEngine
from .accounting_setup import verify_chart_of_accounts
from .models import (
    CashierShift,
    Customer,
    InventoryMovement,
    Payment,
    Product,
    Refund,
    RefundItem,
    Sale,
    SaleItem,
    User,
)
from .permissions import Perm, has_permission

logger = logging.getLogger(__name__)

REFUND_METHODS = frozenset({"cash", "mobile_money", "card", "credit"})


def _generate_refund_number(db: Session, user: User) -> str:
    while True:
        num = f"RF{''.join(random.choices(string.digits, k=8))}"
        exists = (
            tenant_scope.filter_refunds(db, user)
            .filter(Refund.refund_number == num)
            .first()
        )
        if not exists:
            return num


def refunded_quantities_for_sale(db: Session, sale_id: int) -> Dict[int, int]:
    """Sum approved refund qty per sale_item_id."""
    rows = (
        db.query(RefundItem.sale_item_id, RefundItem.quantity)
        .join(Refund, Refund.id == RefundItem.refund_id)
        .filter(Refund.sale_id == sale_id, Refund.status == "approved")
        .all()
    )
    totals: Dict[int, int] = {}
    for sale_item_id, qty in rows:
        totals[sale_item_id] = totals.get(sale_item_id, 0) + int(qty)
    return totals


def sale_refund_summary(db: Session, sale: Sale, user: User) -> dict:
    """Sale lines with remaining refundable quantities."""
    refunded = refunded_quantities_for_sale(db, sale.id)
    items = []
    for si in sale.items:
        product = tenant_scope.get_scoped(db, Product, si.product_id, user)
        already = refunded.get(si.id, 0)
        remaining = max(0, int(si.quantity) - already)
        items.append(
            {
                "sale_item_id": si.id,
                "product_id": si.product_id,
                "product_name": product.name if product else f"Product #{si.product_id}",
                "quantity_sold": int(si.quantity),
                "quantity_refunded": already,
                "quantity_remaining": remaining,
                "unit_price": float(si.unit_price),
                "discount": float(si.discount),
                "line_total": float(si.line_total),
            }
        )
    cashier = tenant_scope.get_scoped(db, User, sale.cashier_id, user)
    return {
        "sale_id": sale.id,
        "created_at": sale.created_at.isoformat() if sale.created_at else None,
        "total": float(sale.total),
        "cashier_name": (cashier.full_name or cashier.username) if cashier else "Unknown",
        "items": items,
        "fully_refunded": all(i["quantity_remaining"] <= 0 for i in items) if items else True,
    }


class RefundLineInput:
    def __init__(self, sale_item_id: int, quantity: int):
        self.sale_item_id = sale_item_id
        self.quantity = quantity


def _build_refund_lines(
    db: Session,
    sale: Sale,
    user: User,
    line_inputs: Optional[List[RefundLineInput]],
    full_refund: bool,
) -> List[dict]:
    refunded = refunded_quantities_for_sale(db, sale.id)
    sale_items = {si.id: si for si in sale.items}
    lines: List[dict] = []

    if full_refund or not line_inputs:
        for si in sale.items:
            remaining = int(si.quantity) - refunded.get(si.id, 0)
            if remaining > 0:
                line_total = (Decimal(str(si.unit_price)) * Decimal(str(remaining))) - (
                    (Decimal(str(si.discount)) / Decimal(str(si.quantity)) * Decimal(str(remaining)))
                    if si.quantity
                    else Decimal("0")
                )
                lines.append(
                    {
                        "sale_item": si,
                        "quantity": remaining,
                        "line_total": line_total.quantize(Decimal("0.01")),
                    }
                )
        return lines

    for inp in line_inputs:
        si = sale_items.get(inp.sale_item_id)
        if si is None:
            raise HTTPException(status_code=400, detail=f"Invalid sale item {inp.sale_item_id}")
        if inp.quantity <= 0:
            raise HTTPException(status_code=400, detail="Refund quantity must be positive")
        remaining = int(si.quantity) - refunded.get(si.id, 0)
        if inp.quantity > remaining:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot refund {inp.quantity} of item {si.id}; only {remaining} remaining",
            )
        line_total = (Decimal(str(si.unit_price)) * Decimal(str(inp.quantity))) - (
            (Decimal(str(si.discount)) / Decimal(str(si.quantity)) * Decimal(str(inp.quantity)))
            if si.quantity
            else Decimal("0")
        )
        lines.append(
            {
                "sale_item": si,
                "quantity": inp.quantity,
                "line_total": line_total.quantize(Decimal("0.01")),
            }
        )
    return lines


def create_refund(
    db: Session,
    user: User,
    *,
    sale_id: int,
    reason: str,
    refund_method: str,
    notes: Optional[str] = None,
    full_refund: bool = False,
    items: Optional[List[RefundLineInput]] = None,
) -> Refund:
    sale = tenant_scope.require_sale(db, sale_id, user)
    if not reason.strip():
        raise HTTPException(status_code=400, detail="Refund reason is required")
    if refund_method not in REFUND_METHODS:
        raise HTTPException(status_code=400, detail="Invalid refund method")

    lines = _build_refund_lines(db, sale, user, items, full_refund)
    if not lines:
        raise HTTPException(status_code=400, detail="Nothing left to refund on this sale")

    amount = sum((ln["line_total"] for ln in lines), Decimal("0"))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Refund amount must be positive")

    refund_type = "full" if full_refund or len(lines) == len(sale.items) else "partial"
    auto_approve = has_permission(user, Perm.APPROVE_REFUNDS)

    refund = Refund(
        sale_id=sale.id,
        refund_number=_generate_refund_number(db, user),
        status="approved" if auto_approve else "pending",
        refund_type=refund_type,
        amount=amount,
        reason=reason.strip(),
        refund_method=refund_method,
        requested_by_id=user.id,
        approved_by_id=user.id if auto_approve else None,
        approved_at=datetime.utcnow() if auto_approve else None,
        notes=notes,
        tenant_id=tenant_scope.tenant_id_for_row(user),
    )
    db.add(refund)
    db.flush()

    for ln in lines:
        si = ln["sale_item"]
        db.add(
            RefundItem(
                refund_id=refund.id,
                sale_item_id=si.id,
                product_id=si.product_id,
                quantity=ln["quantity"],
                unit_price=si.unit_price,
                discount=si.discount,
                line_total=ln["line_total"],
            )
        )

    if auto_approve:
        _apply_refund_effects(db, refund, sale, user)

    db.commit()
    db.refresh(refund)
    return refund


def approve_refund(db: Session, user: User, refund_id: int) -> Refund:
    if not has_permission(user, Perm.APPROVE_REFUNDS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied: approve_refunds")

    refund = tenant_scope.require_refund(db, refund_id, user)
    if refund.status != "pending":
        raise HTTPException(status_code=400, detail=f"Refund is already {refund.status}")

    sale = tenant_scope.require_sale(db, refund.sale_id, user)
    refund.status = "approved"
    refund.approved_by_id = user.id
    refund.approved_at = datetime.utcnow()

    _apply_refund_effects(db, refund, sale, user)
    db.commit()
    db.refresh(refund)
    return refund


def reject_refund(db: Session, user: User, refund_id: int, rejection_reason: Optional[str] = None) -> Refund:
    if not has_permission(user, Perm.APPROVE_REFUNDS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied: approve_refunds")

    refund = tenant_scope.require_refund(db, refund_id, user)
    if refund.status != "pending":
        raise HTTPException(status_code=400, detail=f"Refund is already {refund.status}")

    refund.status = "rejected"
    refund.rejected_by_id = user.id
    refund.rejected_at = datetime.utcnow()
    refund.rejection_reason = (rejection_reason or "").strip() or None
    db.commit()
    db.refresh(refund)
    return refund


def _apply_refund_effects(db: Session, refund: Refund, sale: Sale, user: User) -> None:
    """Restore stock, adjust shift/customer balances, post accounting."""
    db.refresh(refund)
    for ri in refund.items:
        product = tenant_scope.require_product(db, ri.product_id, user)
        product.stock_qty += float(ri.quantity)
        db.add(
            InventoryMovement(
                product_id=product.id,
                change_qty=float(ri.quantity),
                reason=f"Refund {refund.refund_number}",
            )
        )

    if sale.shift_id:
        shift = tenant_scope.require_shift(db, sale.shift_id, user)
        ratio = Decimal(str(refund.amount)) / Decimal(str(sale.total)) if sale.total else Decimal("0")
        shift.total_sales = max(Decimal("0"), Decimal(str(shift.total_sales)) - Decimal(str(refund.amount)))
        if ratio > 0:
            _adjust_shift_payment(shift, sale, refund, ratio)

    if refund.refund_method == "credit" and sale.customer_id:
        customer = tenant_scope.require_customer(db, sale.customer_id, user)
        customer.credit_balance = max(
            Decimal("0"),
            Decimal(str(customer.credit_balance)) - Decimal(str(refund.amount)),
        )

    try:
        if verify_chart_of_accounts(db):
            AccountingEngine(db).post_refund(refund)
    except Exception as e:
        db.rollback()
        logger.error("Refund accounting failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing refund: {e}") from e


def _adjust_shift_payment(shift: CashierShift, sale: Sale, refund: Refund, ratio: Decimal) -> None:
    """Reduce shift payment totals proportionally to refund amount by method."""
    payments = {p.method: Decimal(str(p.amount)) for p in sale.payments}
    total_paid = sum(payments.values(), Decimal("0"))
    if total_paid <= 0:
        return
    refund_amt = Decimal(str(refund.amount))
    method = refund.refund_method
    share = refund_amt
    if method == "cash":
        shift.total_cash = max(Decimal("0"), Decimal(str(shift.total_cash)) - share)
    elif method == "mobile_money":
        shift.total_mobile_money = max(Decimal("0"), Decimal(str(shift.total_mobile_money)) - share)
    elif method == "card":
        shift.total_card = max(Decimal("0"), Decimal(str(shift.total_card)) - share)
    elif method == "credit":
        shift.total_credit = max(Decimal("0"), Decimal(str(shift.total_credit)) - share)
