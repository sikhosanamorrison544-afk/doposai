"""Customer statement aggregation (sales, payments, credit, layby)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Customer, LaybyCustomer, LaybyPayment, LaybyTransaction, Payment, Sale
from ..tenant_scope import filter_by_tenant, filter_layby_customers, filter_sales_by_branch


def build_customer_statement(
    db: Session,
    customer: Customer,
    user,
    *,
    limit: int = 200,
) -> Dict[str, Any]:
    sales_q = (
        filter_by_tenant(db.query(Sale), Sale, user)
        .filter(Sale.customer_id == customer.id)
        .order_by(Sale.created_at.desc())
        .limit(limit)
    )
    sales_q = filter_sales_by_branch(sales_q, user)
    sales = sales_q.all()

    lines: List[Dict[str, Any]] = []
    for s in sales:
        payments = db.query(Payment).filter(Payment.sale_id == s.id).all()
        pay_summary = ", ".join(f"{p.method}: {float(p.amount):.2f}" for p in payments)
        lines.append({
            "date": s.created_at.strftime("%Y-%m-%d %H:%M"),
            "type": "sale",
            "reference": f"Sale #{s.id}",
            "amount": float(s.total),
            "debit": float(s.total),
            "credit": 0.0,
            "detail": pay_summary or None,
        })
        for p in payments:
            if p.method == "credit":
                lines.append({
                    "date": s.created_at.strftime("%Y-%m-%d %H:%M"),
                    "type": "credit_sale",
                    "reference": f"Sale #{s.id}",
                    "amount": float(p.amount),
                    "debit": float(p.amount),
                    "credit": 0.0,
                    "detail": "On account",
                })

    # Layby activity matched by phone
    if customer.phone:
        layby_customers = (
            filter_layby_customers(db, user)
            .filter(LaybyCustomer.phone == customer.phone)
            .all()
        )
        for lc in layby_customers:
            txs = (
                db.query(LaybyTransaction)
                .filter(LaybyTransaction.customer_id == lc.id)
                .order_by(LaybyTransaction.created_at.desc())
                .limit(50)
                .all()
            )
            for tx in txs:
                lines.append({
                    "date": tx.created_at.strftime("%Y-%m-%d %H:%M"),
                    "type": "layby",
                    "reference": f"Layby {tx.product_name}",
                    "amount": float(tx.total_amount),
                    "debit": float(tx.balance),
                    "credit": float(tx.paid_amount),
                    "detail": f"Paid {float(tx.paid_amount):.2f} / {float(tx.total_amount):.2f}",
                })
                for pay in tx.payments:
                    lines.append({
                        "date": pay.created_at.strftime("%Y-%m-%d %H:%M"),
                        "type": "layby_payment",
                        "reference": pay.receipt_number or f"Layby pay #{pay.id}",
                        "amount": float(pay.amount),
                        "debit": 0.0,
                        "credit": float(pay.amount),
                        "detail": pay.payment_method,
                    })

    lines.sort(key=lambda x: x["date"], reverse=True)

    return {
        "customer_id": customer.id,
        "customer_name": customer.name,
        "customer_phone": customer.phone,
        "customer_email": customer.email,
        "address": customer.address,
        "balance": float(customer.credit_balance or 0),
        "generated_at": datetime.utcnow().isoformat(),
        "lines": lines,
    }
