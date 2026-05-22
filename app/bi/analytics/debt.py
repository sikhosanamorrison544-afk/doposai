"""Debtor and layby aggregates for BI."""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import tenant_scope
from ...models import Customer, LaybyTransaction, User


def debt_metrics(db: Session, user: User) -> Dict[str, Any]:
    credit_debtors = (
        tenant_scope.filter_customers(db, user)
        .filter(Customer.credit_balance > 0)
        .order_by(Customer.credit_balance.desc())
        .limit(15)
        .all()
    )
    credit_total = sum(float(c.credit_balance or 0) for c in credit_debtors)

    layby_rows = (
        tenant_scope.filter_layby_transactions(db, user)
        .filter(LaybyTransaction.status == "active")
        .order_by(LaybyTransaction.balance.desc())
        .limit(15)
        .all()
    )
    layby_total = sum(float(t.balance or 0) for t in layby_rows)

    return {
        "outstanding_credit_debt": round(credit_total, 2),
        "outstanding_layby_balance": round(layby_total, 2),
        "total_outstanding_debt": round(credit_total + layby_total, 2),
        "top_debtors_credit": [
            {
                "customer_id": c.id,
                "name": c.name,
                "phone": c.phone,
                "balance": float(c.credit_balance or 0),
            }
            for c in credit_debtors
        ],
        "top_layby_balances": [
            {
                "transaction_id": t.id,
                "product_name": t.product_name,
                "balance": float(t.balance or 0),
                "total_amount": float(t.total_amount or 0),
                "paid_amount": float(t.paid_amount or 0),
            }
            for t in layby_rows
        ],
    }
