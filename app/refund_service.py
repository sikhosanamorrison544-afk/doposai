"""Refund request, approval, stock reversal, and accounting.

Operational integrity (Section 6):
- Client may supply sale_item_id + quantity only; amounts come from SaleItem.
- Pending refunds do **not** reserve quantity (documented); approval re-checks
  remaining capacity against other **approved** refunds and rejects over-refunds.
- Status transitions: pending → approved | rejected | cancelled only.
- Approval is idempotent for side effects; invalid re-approval returns 409.
- Effects run in the caller's transaction; failure rolls back status + stock + GL.
"""
from __future__ import annotations

import logging
import random
import string
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Set

from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from . import tenant_scope
from .accounting_engine import AccountingEngine
from .accounting_models import JournalEntry
from .accounting_setup import verify_chart_of_accounts
from .models import (
    CashierShift,
    Customer,
    InventoryMovement,
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
VALID_STATUSES = frozenset({"pending", "approved", "rejected", "cancelled"})
# Pending does not reserve capacity — only approved refunds consume it.
PENDING_RESERVES_QUANTITY = False


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


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _cent(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def refunded_quantities_for_sale(
    db: Session,
    sale_id: int,
    *,
    exclude_refund_id: Optional[int] = None,
) -> Dict[int, int]:
    """Sum **approved** refund qty per sale_item_id (pending does not consume)."""
    q = (
        db.query(RefundItem.sale_item_id, RefundItem.quantity)
        .join(Refund, Refund.id == RefundItem.refund_id)
        .filter(Refund.sale_id == sale_id, Refund.status == "approved")
    )
    if exclude_refund_id is not None:
        q = q.filter(Refund.id != exclude_refund_id)
    totals: Dict[int, int] = {}
    for sale_item_id, qty in q.all():
        totals[sale_item_id] = totals.get(sale_item_id, 0) + int(qty)
    return totals


def approved_refund_amounts_for_sale(
    db: Session,
    sale_id: int,
    *,
    exclude_refund_id: Optional[int] = None,
) -> Decimal:
    """Sum of approved refund header amounts for a sale."""
    q = db.query(Refund.amount).filter(
        Refund.sale_id == sale_id, Refund.status == "approved"
    )
    if exclude_refund_id is not None:
        q = q.filter(Refund.id != exclude_refund_id)
    return sum((_d(a) for (a,) in q.all()), Decimal("0"))


def remaining_refundable_amount(db: Session, sale: Sale, *, exclude_refund_id: Optional[int] = None) -> Decimal:
    """Sale.total minus previously approved refund amounts (header-discount safe)."""
    already = approved_refund_amounts_for_sale(
        db, sale.id, exclude_refund_id=exclude_refund_id
    )
    return max(Decimal("0"), _d(sale.total) - already)


def sale_refund_summary(db: Session, sale: Sale, user: User) -> dict:
    """Sale lines with remaining refundable quantities (approved consumption only)."""
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
    rem_amt = remaining_refundable_amount(db, sale)
    return {
        "sale_id": sale.id,
        "created_at": sale.created_at.isoformat() if sale.created_at else None,
        "total": float(sale.total),
        "amount_remaining": float(rem_amt),
        "pending_reserves_quantity": PENDING_RESERVES_QUANTITY,
        "cashier_name": (cashier.full_name or cashier.username) if cashier else "Unknown",
        "items": items,
        "fully_refunded": all(i["quantity_remaining"] <= 0 for i in items) if items else True,
    }


class RefundLineInput:
    def __init__(self, sale_item_id: int, quantity: int):
        self.sale_item_id = sale_item_id
        self.quantity = quantity


def _line_refund_amount(si: SaleItem, qty: int) -> Decimal:
    """Authoritative line refund value from historical SaleItem (not client)."""
    sold = int(si.quantity)
    if sold <= 0 or qty <= 0:
        return Decimal("0.00")
    # Prefer proportional line_total (includes line discount); fall back to unit×qty.
    line_total = _d(si.line_total)
    if line_total:
        return _cent(line_total * Decimal(qty) / Decimal(sold))
    unit = _d(si.unit_price)
    disc = _d(si.discount)
    return _cent(unit * Decimal(qty) - (disc / Decimal(sold) * Decimal(qty)))


def _line_discount_share(si: SaleItem, qty: int) -> Decimal:
    sold = int(si.quantity)
    if sold <= 0 or qty <= 0:
        return Decimal("0.00")
    return _cent(_d(si.discount) * Decimal(qty) / Decimal(sold))


def _build_refund_lines(
    db: Session,
    sale: Sale,
    user: User,
    line_inputs: Optional[List[RefundLineInput]],
    full_refund: bool,
    *,
    exclude_refund_id: Optional[int] = None,
) -> List[dict]:
    refunded = refunded_quantities_for_sale(
        db, sale.id, exclude_refund_id=exclude_refund_id
    )
    sale_items = {si.id: si for si in sale.items}
    lines: List[dict] = []
    seen: Set[int] = set()

    if full_refund or not line_inputs:
        for si in sale.items:
            remaining = int(si.quantity) - refunded.get(si.id, 0)
            if remaining > 0:
                lines.append(
                    {
                        "sale_item": si,
                        "quantity": remaining,
                        "line_total": _line_refund_amount(si, remaining),
                        "discount": _line_discount_share(si, remaining),
                    }
                )
        return lines

    for inp in line_inputs:
        if inp.sale_item_id in seen:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate sale_item_id {inp.sale_item_id} in refund request",
            )
        seen.add(inp.sale_item_id)
        si = sale_items.get(inp.sale_item_id)
        if si is None:
            raise HTTPException(status_code=400, detail=f"Invalid sale item {inp.sale_item_id}")
        if not isinstance(inp.quantity, int) or inp.quantity <= 0:
            raise HTTPException(status_code=400, detail="Refund quantity must be a positive integer")
        remaining = int(si.quantity) - refunded.get(si.id, 0)
        if inp.quantity > remaining:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot refund {inp.quantity} of item {si.id}; only {remaining} remaining",
            )
        lines.append(
            {
                "sale_item": si,
                "quantity": inp.quantity,
                "line_total": _line_refund_amount(si, inp.quantity),
                "discount": _line_discount_share(si, inp.quantity),
            }
        )
    return lines


def _assert_sale_amount_cap(
    db: Session, sale: Sale, amount: Decimal, *, exclude_refund_id: Optional[int] = None
) -> None:
    remaining = remaining_refundable_amount(db, sale, exclude_refund_id=exclude_refund_id)
    if amount > remaining:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Refund amount {amount} exceeds remaining refundable sale total "
                f"{remaining} (sale total {_d(sale.total)})"
            ),
        )


def _assert_refund_items_still_refundable(db: Session, refund: Refund, sale: Sale) -> None:
    """Re-check capacity at approval time (pending does not reserve)."""
    if not refund.items:
        # Legacy itemless refunds must not be newly approved operationally.
        raise HTTPException(
            status_code=409,
            detail="Legacy itemless refund cannot be approved; create a new line-item refund",
        )
    refunded = refunded_quantities_for_sale(db, sale.id, exclude_refund_id=refund.id)
    sale_items = {si.id: si for si in sale.items}
    amount = Decimal("0")
    for ri in refund.items:
        si = sale_items.get(ri.sale_item_id)
        if si is None:
            raise HTTPException(
                status_code=400,
                detail=f"Refund item references invalid sale item {ri.sale_item_id}",
            )
        qty = int(ri.quantity)
        if qty <= 0:
            raise HTTPException(status_code=400, detail="Refund item quantity must be positive")
        remaining = int(si.quantity) - refunded.get(si.id, 0)
        if qty > remaining:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot approve: refund needs {qty} of item {si.id} "
                    f"but only {remaining} remaining after other approved refunds"
                ),
            )
        # Authoritative amount from sale line (ignore stored client-era values for cap)
        amount += _line_refund_amount(si, qty)
        refunded[si.id] = refunded.get(si.id, 0) + qty

    amount = _cent(amount)
    # Prefer stored header amount when it matches computed; always cap by Sale.total.
    header = _cent(_d(refund.amount))
    check_amt = header if header > 0 else amount
    if check_amt > remaining_refundable_amount(db, sale, exclude_refund_id=refund.id):
        raise HTTPException(
            status_code=409,
            detail="Cannot approve: refund would exceed remaining refundable sale amount",
        )


def _lock_refund(db: Session, refund_id: int, user: User) -> Refund:
    q = (
        tenant_scope.filter_refunds(db, user)
        .filter(Refund.id == refund_id)
        .with_for_update()
    )
    refund = q.first()
    if refund is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Refund not found")
    return refund


def _lock_sale(db: Session, sale_id: int, user: User) -> Sale:
    q = (
        tenant_scope.filter_sales(db, user)
        .filter(Sale.id == sale_id)
        .with_for_update()
    )
    sale = q.first()
    if sale is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    # Eager-load items under same session
    _ = sale.items
    return sale


def _assert_tenant_alignment(user: User, sale: Sale, refund: Optional[Refund] = None) -> None:
    if not tenant_scope.same_tenant(user.tenant_id, sale.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    if refund is not None and not tenant_scope.same_tenant(user.tenant_id, refund.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Refund not found")
    if refund is not None and refund.sale_id != sale.id:
        raise HTTPException(status_code=400, detail="Refund does not belong to sale")


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
    if not has_permission(user, Perm.REQUEST_REFUNDS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: request_refunds",
        )

    sale = _lock_sale(db, sale_id, user)
    reason_clean = (reason or "").strip()
    if not reason_clean:
        raise HTTPException(status_code=400, detail="Refund reason is required")
    if len(reason_clean) > 500:
        raise HTTPException(status_code=400, detail="Refund reason too long")
    if refund_method not in REFUND_METHODS:
        raise HTTPException(status_code=400, detail="Invalid refund method")

    lines = _build_refund_lines(db, sale, user, items, full_refund)
    if not lines:
        raise HTTPException(status_code=400, detail="Nothing left to refund on this sale")

    amount = _cent(sum((ln["line_total"] for ln in lines), Decimal("0")))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Refund amount must be positive")
    _assert_sale_amount_cap(db, sale, amount)

    refund_type = "full" if full_refund or len(lines) == len(sale.items) else "partial"
    auto_approve = has_permission(user, Perm.APPROVE_REFUNDS)

    refund = Refund(
        sale_id=sale.id,
        refund_number=_generate_refund_number(db, user),
        status="approved" if auto_approve else "pending",
        refund_type=refund_type,
        amount=amount,
        reason=reason_clean,
        refund_method=refund_method,
        requested_by_id=user.id,
        approved_by_id=user.id if auto_approve else None,
        approved_at=datetime.utcnow() if auto_approve else None,
        notes=(notes.strip() if notes else None),
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
                discount=ln["discount"],
                line_total=ln["line_total"],
            )
        )
    db.flush()

    if auto_approve:
        db.refresh(refund)
        _apply_refund_effects(db, refund, sale, user)

    db.commit()
    db.refresh(refund)
    return refund


def approve_refund(db: Session, user: User, refund_id: int) -> Refund:
    if not has_permission(user, Perm.APPROVE_REFUNDS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: approve_refunds",
        )

    refund = _lock_refund(db, refund_id, user)
    if refund.status == "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Refund is already approved",
        )
    if refund.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid transition: {refund.status} → approved",
        )

    sale = _lock_sale(db, refund.sale_id, user)
    _assert_tenant_alignment(user, sale, refund)
    _assert_refund_items_still_refundable(db, refund, sale)

    # Capture audit once — never overwrite on retry (guarded by status above).
    refund.status = "approved"
    refund.approved_by_id = user.id
    refund.approved_at = datetime.utcnow()

    try:
        _apply_refund_effects(db, refund, sale, user)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error("Refund approval failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error processing refund: {e}"
        ) from e

    db.refresh(refund)
    return refund


def reject_refund(
    db: Session, user: User, refund_id: int, rejection_reason: Optional[str] = None
) -> Refund:
    if not has_permission(user, Perm.APPROVE_REFUNDS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: approve_refunds",
        )

    refund = _lock_refund(db, refund_id, user)
    if refund.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid transition: {refund.status} → rejected",
        )

    refund.status = "rejected"
    refund.rejected_by_id = user.id
    refund.rejected_at = datetime.utcnow()
    refund.rejection_reason = (rejection_reason or "").strip() or None
    db.commit()
    db.refresh(refund)
    return refund


def cancel_refund(db: Session, user: User, refund_id: int) -> Refund:
    """Cancel a pending refund. Requester or approver may cancel."""
    can_request = has_permission(user, Perm.REQUEST_REFUNDS)
    can_approve = has_permission(user, Perm.APPROVE_REFUNDS)
    if not (can_request or can_approve):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: cancel refund",
        )

    refund = _lock_refund(db, refund_id, user)
    if refund.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid transition: {refund.status} → cancelled",
        )
    if not can_approve and refund.requested_by_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the requester or an approver can cancel this refund",
        )

    refund.status = "cancelled"
    # Reuse rejected_* columns only when no dedicated cancel fields exist —
    # store actor in notes suffix is avoided; rejected_by unused for cancel.
    # Prefer not overwriting rejection fields. Stamp via notes if empty.
    if not refund.notes:
        refund.notes = f"Cancelled by user #{user.id}"
    db.commit()
    db.refresh(refund)
    return refund


def _inventory_already_restored(db: Session, refund: Refund) -> bool:
    marker = f"Refund {refund.refund_number}"
    return (
        db.query(InventoryMovement.id)
        .filter(InventoryMovement.reason == marker)
        .first()
        is not None
    )


def _refund_journal_exists(db: Session, refund_id: int) -> Optional[JournalEntry]:
    return (
        db.query(JournalEntry)
        .filter(
            JournalEntry.reference_type == "REFUND",
            JournalEntry.reference_id == refund_id,
        )
        .first()
    )


def _apply_refund_effects(db: Session, refund: Refund, sale: Sale, user: User) -> None:
    """Restore stock, adjust shift/customer balances, post accounting (once)."""
    # Do not refresh(refund) here — callers may have set status/audit fields
    # that are not yet flushed; a refresh would wipe them.
    if not refund.items:
        # Ensure relationship is loaded
        db.query(RefundItem).filter(RefundItem.refund_id == refund.id).all()
    db.flush()  # persist status/audit before side effects
    items = list(refund.items)
    if not items:
        raise HTTPException(
            status_code=409,
            detail="Cannot apply effects for itemless legacy refund",
        )

    already_stock = _inventory_already_restored(db, refund)
    if not already_stock:
        for ri in items:
            product = (
                db.query(Product)
                .filter(Product.id == ri.product_id)
                .with_for_update()
                .one_or_none()
            )
            if product is None or not tenant_scope.row_visible(
                getattr(product, "tenant_id", None), user
            ):
                raise HTTPException(
                    status_code=404, detail=f"Product {ri.product_id} not found"
                )
            change = float(ri.quantity)
            db.execute(
                update(Product)
                .where(Product.id == product.id)
                .values(stock_qty=Product.stock_qty + change)
            )
            db.add(
                InventoryMovement(
                    product_id=product.id,
                    change_qty=change,
                    reason=f"Refund {refund.refund_number}",
                )
            )
        db.flush()

    if sale.shift_id:
        shift = tenant_scope.require_shift(db, sale.shift_id, user)
        ratio = (
            _d(refund.amount) / _d(sale.total) if sale.total else Decimal("0")
        )
        shift.total_sales = max(
            Decimal("0"), _d(shift.total_sales) - _d(refund.amount)
        )
        if ratio > 0:
            _adjust_shift_payment(shift, sale, refund)

    if refund.refund_method == "credit" and sale.customer_id:
        customer = tenant_scope.require_customer(db, sale.customer_id, user)
        customer.credit_balance = max(
            Decimal("0"),
            _d(customer.credit_balance) - _d(refund.amount),
        )

    try:
        if verify_chart_of_accounts(db):
            if _refund_journal_exists(db, refund.id) is None:
                AccountingEngine(db).post_refund(refund)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Refund accounting failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error processing refund: {e}"
        ) from e


def _adjust_shift_payment(shift: CashierShift, sale: Sale, refund: Refund) -> None:
    """Reduce shift payment totals by refund method (once per approval)."""
    refund_amt = _d(refund.amount)
    method = refund.refund_method
    if method == "cash":
        shift.total_cash = max(Decimal("0"), _d(shift.total_cash) - refund_amt)
    elif method == "mobile_money":
        shift.total_mobile_money = max(
            Decimal("0"), _d(shift.total_mobile_money) - refund_amt
        )
    elif method == "card":
        shift.total_card = max(Decimal("0"), _d(shift.total_card) - refund_amt)
    elif method == "credit":
        shift.total_credit = max(Decimal("0"), _d(shift.total_credit) - refund_amt)
