"""Expense ledger HTTP API."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db
from .expense_service import (
    approve_expense,
    create_expense,
    reject_expense,
    void_expense,
)
from .finance_service import EXPENSE_CATEGORIES, EXPENSE_CATEGORY_LABELS
from .models import Expense, User
from .permissions import Perm, dep_perm
from . import tenant_scope

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


class ExpenseCreate(BaseModel):
    amount: Decimal
    category: str
    description: str
    payment_method: str = "cash"
    expense_date: Optional[datetime] = None
    branch_id: Optional[int] = None
    supplier_or_payee: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    auto_approve: bool = True


class ExpenseReject(BaseModel):
    reason: Optional[str] = None


class ExpenseVoid(BaseModel):
    reason: Optional[str] = None


class ExpenseRead(BaseModel):
    id: int
    tenant_id: Optional[int] = None
    branch_id: Optional[int] = None
    expense_date: datetime
    category: str
    category_label: str
    description: str
    amount: Decimal
    payment_method: str
    supplier_or_payee: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_by: int
    created_at: datetime
    updated_at: datetime
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    cash_movement_id: Optional[int] = None

    class Config:
        from_attributes = True


def _to_read(e: Expense) -> ExpenseRead:
    return ExpenseRead(
        id=e.id,
        tenant_id=e.tenant_id,
        branch_id=e.branch_id,
        expense_date=e.expense_date,
        category=e.category,
        category_label=EXPENSE_CATEGORY_LABELS.get(e.category, e.category),
        description=e.description,
        amount=e.amount,
        payment_method=e.payment_method,
        supplier_or_payee=e.supplier_or_payee,
        reference=e.reference,
        notes=e.notes,
        status=e.status,
        created_by=e.created_by,
        created_at=e.created_at,
        updated_at=e.updated_at,
        approved_by=e.approved_by,
        approved_at=e.approved_at,
        cash_movement_id=e.cash_movement_id,
    )


@router.get("/categories")
async def list_categories(
    current_user: User = Depends(dep_perm(Perm.VIEW_EXPENSES)),
):
    return [
        {"value": c, "label": EXPENSE_CATEGORY_LABELS.get(c, c)}
        for c in EXPENSE_CATEGORIES
    ]


@router.get("", response_model=List[ExpenseRead])
async def list_expenses(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    status: Optional[str] = None,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.VIEW_EXPENSES)),
):
    q = tenant_scope.filter_expenses(db, current_user).order_by(
        Expense.expense_date.desc(), Expense.id.desc()
    )
    if from_date:
        q = q.filter(
            Expense.expense_date >= datetime.combine(from_date, datetime.min.time())
        )
    if to_date:
        q = q.filter(
            Expense.expense_date <= datetime.combine(to_date, datetime.max.time())
        )
    if status:
        q = q.filter(Expense.status == status.strip().lower())
    if branch_id is not None:
        q = q.filter(Expense.branch_id == branch_id)
    return [_to_read(e) for e in q.limit(500).all()]


@router.post("", response_model=ExpenseRead)
async def post_expense(
    body: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.MANAGE_EXPENSES)),
):
    expense = create_expense(
        db,
        current_user,
        amount=body.amount,
        category=body.category,
        description=body.description,
        payment_method=body.payment_method,
        expense_date=body.expense_date,
        branch_id=body.branch_id,
        supplier_or_payee=body.supplier_or_payee,
        reference=body.reference,
        notes=body.notes,
        auto_approve=body.auto_approve,
    )
    db.commit()
    db.refresh(expense)
    return _to_read(expense)


@router.get("/{expense_id}", response_model=ExpenseRead)
async def get_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.VIEW_EXPENSES)),
):
    expense = tenant_scope.filter_expenses(db, current_user).filter(
        Expense.id == expense_id
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return _to_read(expense)


@router.post("/{expense_id}/approve", response_model=ExpenseRead)
async def approve_expense_route(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.MANAGE_EXPENSES)),
):
    expense = tenant_scope.filter_expenses(db, current_user).filter(
        Expense.id == expense_id
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    approve_expense(db, expense, current_user)
    db.commit()
    db.refresh(expense)
    return _to_read(expense)


@router.post("/{expense_id}/reject", response_model=ExpenseRead)
async def reject_expense_route(
    expense_id: int,
    body: ExpenseReject,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.MANAGE_EXPENSES)),
):
    expense = tenant_scope.filter_expenses(db, current_user).filter(
        Expense.id == expense_id
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    reject_expense(db, expense, current_user, reason=body.reason)
    db.commit()
    db.refresh(expense)
    return _to_read(expense)


@router.post("/{expense_id}/void", response_model=ExpenseRead)
async def void_expense_route(
    expense_id: int,
    body: ExpenseVoid,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.MANAGE_EXPENSES)),
):
    expense = tenant_scope.filter_expenses(db, current_user).filter(
        Expense.id == expense_id
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    void_expense(db, expense, current_user, reason=body.reason)
    db.commit()
    db.refresh(expense)
    return _to_read(expense)
