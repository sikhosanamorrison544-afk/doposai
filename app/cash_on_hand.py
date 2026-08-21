"""
Authoritative cash activity for a selected reporting date range.

    cash_on_hand = cash_payments − withdrawals − cash_expense_outflows − cash_refunds

Where:
  * cash_payments          — Payment.method == \"cash\", sale created in range, tenant-scoped
  * withdrawals            — Withdrawal rows in range (cash drawer removals, not P&L expenses)
  * cash_expense_outflows  — CashMovement outflows for **approved** Expenses paid in cash
  * cash_refunds           — Refund status approved + refund_method cash, in range

Withdrawals and expense cash movements are separate ledgers so the same cash exit
is never counted twice (expenses do not create Withdrawal rows). Voided expenses
are excluded from cash_expense_outflows via join on Expense.status == approved.

Clearing note: a standalone expense_payment Withdrawal reduces cash via Withdrawals
only; it does not create an Expense. Do not also book a cash Expense for the same
physical payment (see withdrawal_purpose module docstring).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import tenant_scope
from .finance_service import refund_effective_at_expr
from .models import CashMovement, Expense, Payment, Refund, Sale, User, Withdrawal


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def compute_cash_on_hand(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    branch_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Return cash activity components for ``[start, end]``.

    When ``branch_id`` is None (all branches / tenant):
      available=True, full formula including withdrawals.

    When ``branch_id`` is set:
      available=False — withdrawals cannot be attributed to a branch.
      ``cash_on_hand`` is null so clients must not show a till-like total.
    """
    if branch_id is not None:
        return {
            "cash_on_hand": None,
            "cash_payments": Decimal("0"),
            "withdrawals_total": Decimal("0"),
            "cash_expense_outflows": Decimal("0"),
            "cash_refunds": Decimal("0"),
            "withdrawals_included": False,
            "available": False,
            "scope": "branch",
            "subtitle": "Unavailable for individual branches",
            "note": (
                "Withdrawals are not assigned to branches, so branch Cash on hand "
                "would omit cash removals and overstate the balance. Select All "
                "branches for the period cash activity figure."
            ),
            "reason": "Withdrawals are not assigned to branches",
            "as_of_start": start.isoformat(),
            "as_of_end": end.isoformat(),
            "meaning": "period",
        }

    cash_pay_q = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .join(Sale, Payment.sale_id == Sale.id)
        .filter(
            Payment.method == "cash",
            Sale.created_at >= start,
            Sale.created_at <= end,
            tenant_scope.sale_tenant_match(user),
        )
    )
    cash_payments = _d(cash_pay_q.scalar())

    refund_q = (
        db.query(func.coalesce(func.sum(Refund.amount), 0))
        .join(Sale, Refund.sale_id == Sale.id)
        .filter(
            Refund.status == "approved",
            Refund.refund_method == "cash",
            refund_effective_at_expr() >= start,
            refund_effective_at_expr() <= end,
            tenant_scope.sale_tenant_match(user),
        )
    )
    if user.tenant_id is None:
        refund_q = refund_q.filter(Refund.tenant_id.is_(None))
    else:
        refund_q = refund_q.filter(Refund.tenant_id == user.tenant_id)
    cash_refunds = _d(refund_q.scalar())

    wd_q = (
        tenant_scope.filter_withdrawals(db, user)
        .filter(Withdrawal.created_at >= start, Withdrawal.created_at <= end)
        .with_entities(func.coalesce(func.sum(Withdrawal.amount), 0))
    )
    withdrawals_total = _d(wd_q.scalar())

    # Only cash movements for *currently approved* expenses — voided expenses
    # drop out so cash is not permanently reduced after void (no second Withdrawal).
    exp_cash_q = (
        tenant_scope.filter_cash_movements(db, user)
        .join(
            Expense,
            (CashMovement.source_id == Expense.id)
            & (CashMovement.source_type == "expense"),
        )
        .filter(
            CashMovement.direction == "out",
            CashMovement.payment_method == "cash",
            CashMovement.movement_date >= start,
            CashMovement.movement_date <= end,
            Expense.status == "approved",
        )
        .with_entities(func.coalesce(func.sum(CashMovement.amount), 0))
    )
    cash_expense_outflows = _d(exp_cash_q.scalar())

    cash_on_hand = (
        cash_payments - withdrawals_total - cash_expense_outflows - cash_refunds
    )

    return {
        "cash_on_hand": cash_on_hand,
        "cash_payments": cash_payments,
        "withdrawals_total": withdrawals_total,
        "cash_expense_outflows": cash_expense_outflows,
        "cash_refunds": cash_refunds,
        "withdrawals_included": True,
        "available": True,
        "scope": "tenant",
        "subtitle": "Cash activity for selected period",
        "note": (
            "cash payments − withdrawals − approved cash expense outflows − cash refunds; "
            "expense CashMovements and Withdrawals are separate (never both for one payment); "
            "not a live drawer count"
        ),
        "reason": None,
        "as_of_start": start.isoformat(),
        "as_of_end": end.isoformat(),
        "meaning": "period",
    }
