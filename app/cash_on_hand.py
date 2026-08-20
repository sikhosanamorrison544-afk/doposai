"""
Authoritative cash activity for a selected reporting date range.

Same formula as ``GET /api/reports/summary`` when scope is the whole tenant:

    cash_on_hand = cash_payments − withdrawals_total − cash_refunds

Where:
  * cash_payments  — Payment.method == \"cash\", sale created in range, tenant-scoped
  * withdrawals    — all Withdrawal rows in range, tenant-scoped (no branch column)
  * cash_refunds   — Refund status approved + refund_method cash, in range, tenant-scoped

This is a **period** balance for the selected reporting dates, not a live drawer
snapshot and not shift ``starting_cash``.

Branch note: Withdrawal has no ``branch_id``. Individual-branch Cash on hand is
therefore **unavailable** (not a partial figure), so Overview never presents an
overstated branch till balance that omits withdrawals.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import tenant_scope
from .models import Payment, Refund, Sale, User, Withdrawal


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
            Refund.created_at >= start,
            Refund.created_at <= end,
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

    cash_on_hand = cash_payments - withdrawals_total - cash_refunds

    return {
        "cash_on_hand": cash_on_hand,
        "cash_payments": cash_payments,
        "withdrawals_total": withdrawals_total,
        "cash_refunds": cash_refunds,
        "withdrawals_included": True,
        "available": True,
        "scope": "tenant",
        "subtitle": "Cash activity for selected period",
        "note": (
            "cash payments − withdrawals − approved cash refunds "
            "(same as /api/reports/summary); not a live drawer count"
        ),
        "reason": None,
        "as_of_start": start.isoformat(),
        "as_of_end": end.isoformat(),
        "meaning": "period",
    }
