"""Sales aggregates for BI."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import tenant_scope
from ...models import Payment, Product, Sale, SaleItem, User


def sales_metrics(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    prev_start: datetime,
    prev_end: datetime,
) -> Dict[str, Any]:
    def _revenue(s: datetime, e: datetime) -> float:
        v = (
            db.query(func.coalesce(func.sum(Sale.total), 0))
            .filter(
                Sale.created_at >= s,
                Sale.created_at < e,
                tenant_scope.sale_tenant_match(user),
            )
            .scalar()
        )
        return float(v or 0)

    def _tx_count(s: datetime, e: datetime) -> int:
        return int(
            db.query(func.count(Sale.id))
            .filter(
                Sale.created_at >= s,
                Sale.created_at < e,
                tenant_scope.sale_tenant_match(user),
            )
            .scalar()
            or 0
        )

    sales_this = _revenue(start, end)
    sales_last = _revenue(prev_start, prev_end)
    change_pct = _pct_change(sales_this, sales_last)

    payment_mix = (
        db.query(Payment.method, func.sum(Payment.amount).label("amt"))
        .join(Sale, Payment.sale_id == Sale.id)
        .filter(
            Sale.created_at >= start,
            Sale.created_at < end,
            tenant_scope.sale_tenant_match(user),
        )
        .group_by(Payment.method)
        .all()
    )

    top_products = _top_products(db, user, start, end, limit=10, order="desc")
    worst_products = _top_products(db, user, start, end, limit=10, order="asc")

    daily = (
        db.query(
            func.date(Sale.created_at).label("day"),
            func.sum(Sale.total).label("revenue"),
            func.count(Sale.id).label("tx"),
        )
        .filter(
            Sale.created_at >= start,
            Sale.created_at < end,
            tenant_scope.sale_tenant_match(user),
        )
        .group_by(func.date(Sale.created_at))
        .order_by(func.date(Sale.created_at))
        .all()
    )

    return {
        "sales_this_period": sales_this,
        "sales_last_period": sales_last,
        "revenue_change_percent": change_pct,
        "transactions_this_period": _tx_count(start, end),
        "transactions_last_period": _tx_count(prev_start, prev_end),
        "average_ticket": round(sales_this / max(_tx_count(start, end), 1), 2),
        "payment_mix": {r.method: float(r.amt or 0) for r in payment_mix},
        "top_products": top_products,
        "worst_sellers": worst_products,
        "daily_revenue": [
            {"date": str(r.day), "revenue": float(r.revenue or 0), "transactions": int(r.tx or 0)}
            for r in daily
        ],
    }


def _top_products(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    *,
    limit: int,
    order: str,
) -> List[Dict[str, Any]]:
    q = (
        db.query(
            Product.id,
            Product.name,
            Product.barcode,
            func.sum(SaleItem.quantity).label("qty"),
            func.sum(SaleItem.line_total).label("revenue"),
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.created_at >= start,
            Sale.created_at < end,
            Product.is_active == True,  # noqa: E712
            tenant_scope.sale_tenant_match(user),
            tenant_scope.product_tenant_match(user),
        )
        .group_by(Product.id, Product.name, Product.barcode)
    )
    if order == "desc":
        q = q.order_by(func.sum(SaleItem.line_total).desc())
    else:
        q = q.order_by(func.sum(SaleItem.line_total).asc())
    rows = q.limit(limit).all()
    return [
        {
            "product_id": r.id,
            "name": r.name,
            "barcode": r.barcode,
            "quantity_sold": float(r.qty or 0),
            "revenue": float(r.revenue or 0),
        }
        for r in rows
    ]


def _pct_change(current: float, previous: float) -> float:
    if previous <= 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 2)
