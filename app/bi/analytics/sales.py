"""Sales aggregates for BI."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import tenant_scope
from ...finance_service import payment_method_net_totals, product_period_metrics
from ...models import Payment, Product, Sale, SaleItem, User


def sales_metrics_for_health(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    prev_start: datetime,
    prev_end: datetime,
) -> Dict[str, Any]:
    """Minimal sales aggregates for health score cards (fewer DB round-trips)."""
    sales_this = (
        db.query(func.coalesce(func.sum(Sale.total), 0))
        .filter(
            Sale.created_at >= start,
            Sale.created_at < end,
            tenant_scope.sale_tenant_match(user),
        )
        .scalar()
    )
    sales_last = (
        db.query(func.coalesce(func.sum(Sale.total), 0))
        .filter(
            Sale.created_at >= prev_start,
            Sale.created_at < prev_end,
            tenant_scope.sale_tenant_match(user),
        )
        .scalar()
    )
    sales_this_f = float(sales_this or 0)
    sales_last_f = float(sales_last or 0)
    return {
        "sales_this_period": sales_this_f,
        "sales_last_period": sales_last_f,
        "revenue_change_percent": _pct_change(sales_this_f, sales_last_f),
        "revenue_this_period": sales_this_f,
    }


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

    payment_mix = payment_method_net_totals(
        db, user, start, end, end_exclusive=True
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
        "payment_mix": {k: float(v) for k, v in payment_mix.items()},
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
    rows = product_period_metrics(
        db, user, start, end, end_exclusive=True, active_only=True
    )
    ranked = [r for r in rows if r.gross_units > 0 or r.net_units > 0]
    reverse = order == "desc"
    ranked.sort(key=lambda r: (r.net_revenue, r.net_units), reverse=reverse)
    return [
        {
            "product_id": r.product_id,
            "name": r.name,
            "barcode": r.barcode,
            "quantity_sold": float(r.net_units),
            "revenue": float(r.net_revenue),
        }
        for r in ranked[:limit]
    ]


def _pct_change(current: float, previous: float) -> float:
    if previous <= 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 2)
