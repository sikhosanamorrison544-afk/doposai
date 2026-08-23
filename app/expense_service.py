"""Expense ledger create / approve / void / cash-movement linking.

Lifecycle: ``draft`` → ``approved`` → ``voided`` (or ``draft`` → ``rejected``).

Cash rules (no double counting):
  * Approved cash expense → one CashMovement (source_type=expense); never a Withdrawal.
  * Approved non-cash expense → P&L only; no cash CashMovement.
  * Standalone Withdrawal → till cash only; never an Expense / never Overview expenses.
  * Legacy ``expense_payment`` Withdrawal → clearing account only; not operating expense.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import tenant_scope
from .finance_service import EXPENSE_CATEGORIES, EXPENSE_CATEGORY_ACCOUNT
from .models import CashMovement, Expense, User

STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUS_VOIDED = "voided"
STATUS_REJECTED = "rejected"

# Accept legacy "pending" as draft for migration compatibility
_DRAFT_STATUSES = frozenset({STATUS_DRAFT, "pending"})


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def create_expense(
    db: Session,
    user: User,
    *,
    amount,
    category: str,
    description: str,
    payment_method: str = "cash",
    expense_date: Optional[datetime] = None,
    branch_id: Optional[int] = None,
    supplier_or_payee: Optional[str] = None,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
    auto_approve: bool = False,
    header_branch_id: Optional[str] = None,
) -> Expense:
    from .inventory_service import require_operational_branch

    cat = (category or "").strip().lower()
    if cat not in EXPENSE_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Allowed: {', '.join(EXPENSE_CATEGORIES)}",
        )
    amt = _d(amount)
    if amt <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    desc = (description or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="Description is required")

    method = (payment_method or "cash").strip().lower()
    if method not in {"cash", "mobile_money", "card", "bank_transfer", "other"}:
        raise HTTPException(status_code=400, detail="Invalid payment_method")

    write_branch = require_operational_branch(
        db,
        user,
        explicit_branch_id=branch_id,
        header_branch_id=header_branch_id,
    )

    expense = Expense(
        tenant_id=tenant_scope.tenant_id_for_row(user),
        branch_id=write_branch.id,
        expense_date=expense_date or datetime.utcnow(),
        category=cat,
        description=desc,
        amount=amt,
        payment_method=method,
        supplier_or_payee=(supplier_or_payee or "").strip() or None,
        reference=(reference or "").strip() or None,
        notes=(notes or "").strip() or None,
        status=STATUS_DRAFT,
        created_by=user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(expense)
    db.flush()

    if auto_approve:
        approve_expense(db, expense, user)
    return expense


def _ensure_cash_movement(db: Session, expense: Expense, user: User) -> Optional[CashMovement]:
    """Link a cash outflow once for cash-paid approved expenses (no Withdrawal row)."""
    if expense.payment_method != "cash":
        return None
    if expense.cash_movement_id:
        existing = db.get(CashMovement, expense.cash_movement_id)
        if existing:
            return existing

    # Idempotent: reuse movement already linked by source
    existing = (
        db.query(CashMovement)
        .filter(
            CashMovement.source_type == "expense",
            CashMovement.source_id == expense.id,
            CashMovement.direction == "out",
        )
        .first()
    )
    if existing:
        expense.cash_movement_id = existing.id
        return existing

    movement = CashMovement(
        tenant_id=expense.tenant_id,
        branch_id=expense.branch_id,
        movement_date=expense.expense_date or datetime.utcnow(),
        direction="out",
        amount=expense.amount,
        payment_method="cash",
        source_type="expense",
        source_id=expense.id,
        description=f"Expense #{expense.id}: {expense.category} — {expense.description}",
        created_by=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(movement)
    db.flush()
    expense.cash_movement_id = movement.id
    return movement


def _post_accounting_once(db: Session, expense: Expense) -> None:
    try:
        from .accounting_engine import AccountingEngine
        from .accounting_models import JournalEntry
        from .accounting_setup import verify_chart_of_accounts

        if not verify_chart_of_accounts(db):
            return
        already = (
            db.query(JournalEntry)
            .filter(
                JournalEntry.reference_type == "EXPENSE",
                JournalEntry.reference_id == expense.id,
            )
            .first()
        )
        if already:
            return
        AccountingEngine(db).post_expense(expense)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Accounting post for expense %s skipped: %s", expense.id, exc
        )


def approve_expense(db: Session, expense: Expense, user: User) -> Expense:
    """Idempotent approve: second call is a no-op (no second cash/journal)."""
    if expense.status == STATUS_APPROVED:
        return expense
    if expense.status == STATUS_VOIDED:
        raise HTTPException(status_code=400, detail="Cannot approve a voided expense")
    if expense.status not in _DRAFT_STATUSES | {STATUS_REJECTED}:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve expense in status {expense.status}",
        )

    expense.status = STATUS_APPROVED
    expense.approved_by = user.id
    expense.approved_at = datetime.utcnow()
    expense.updated_at = datetime.utcnow()
    _ensure_cash_movement(db, expense, user)
    _post_accounting_once(db, expense)
    return expense


def reject_expense(db: Session, expense: Expense, user: User, *, reason: Optional[str] = None) -> Expense:
    if expense.status == STATUS_APPROVED:
        raise HTTPException(
            status_code=400,
            detail="Approved expenses cannot be rejected; void them instead",
        )
    if expense.status == STATUS_VOIDED:
        raise HTTPException(status_code=400, detail="Expense is already voided")
    if expense.status == STATUS_REJECTED:
        return expense
    if expense.status not in _DRAFT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject expense in status {expense.status}",
        )
    expense.status = STATUS_REJECTED
    expense.approved_by = user.id
    expense.approved_at = datetime.utcnow()
    expense.updated_at = datetime.utcnow()
    if reason:
        note = (expense.notes or "").strip()
        expense.notes = f"{note}\nRejection: {reason}".strip() if note else f"Rejection: {reason}"
    return expense


def void_expense(db: Session, expense: Expense, user: User, *, reason: Optional[str] = None) -> Expense:
    """
    Void an approved expense (idempotent).

    Removes it from operating expenses and excludes its CashMovement from cash-on-hand
    (movement row kept for audit; cash formula joins only approved expenses).
    """
    if expense.status == STATUS_VOIDED:
        return expense
    if expense.status in _DRAFT_STATUSES | {STATUS_REJECTED}:
        # Cancel before approval — no cash / journal effects
        expense.status = STATUS_VOIDED
        expense.updated_at = datetime.utcnow()
        if reason:
            note = (expense.notes or "").strip()
            expense.notes = f"{note}\nVoided: {reason}".strip() if note else f"Voided: {reason}"
        return expense
    if expense.status != STATUS_APPROVED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot void expense in status {expense.status}",
        )

    expense.status = STATUS_VOIDED
    expense.updated_at = datetime.utcnow()
    if reason:
        note = (expense.notes or "").strip()
        expense.notes = f"{note}\nVoided: {reason}".strip() if note else f"Voided: {reason}"

    try:
        from .accounting_engine import AccountingEngine
        from .accounting_models import JournalEntry
        from .accounting_setup import verify_chart_of_accounts

        if verify_chart_of_accounts(db):
            already = (
                db.query(JournalEntry)
                .filter(
                    JournalEntry.reference_type == "EXPENSE_VOID",
                    JournalEntry.reference_id == expense.id,
                )
                .first()
            )
            if not already:
                AccountingEngine(db).reverse_expense(expense, created_by=user.id)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Accounting reverse for expense %s skipped: %s", expense.id, exc
        )

    return expense


def account_code_for_category(category: str) -> str:
    return EXPENSE_CATEGORY_ACCOUNT.get(category, "6700")
