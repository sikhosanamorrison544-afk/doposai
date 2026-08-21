"""Analytics page queries — refund-aware product rankings and revenue."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, List, Optional

from sqlalchemy import and_, exists, func, select, text
from sqlalchemy.orm import Session

from app import tenant_scope
from app.finance_service import product_period_metrics
from app.models import Product, Sale, SaleItem


def pg_statement_timeout(db: Session, ms: int = 25000) -> None:
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text(f"SET LOCAL statement_timeout = '{ms}'"))
    except Exception:
        pass


def _cutoff(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


def _recent_sale_exists(cutoff: datetime, current_user: Any):
    return (
        select(1)
        .select_from(SaleItem)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .where(
            SaleItem.product_id == Product.id,
            Sale.created_at >= cutoff,
            tenant_scope.sale_tenant_match(current_user),
        )
    )


def _period_product_rows(db: Session, current_user: Any, cutoff: datetime):
    """Refund-aware product metrics from cutoff → now (closed end)."""
    now = datetime.utcnow()
    return product_period_metrics(
        db, current_user, cutoff, now, end_exclusive=False, active_only=True
    )


def build_dashboard_summary(
    db: Session, current_user: Any, days: int, *, fast: bool = False
) -> dict:
    """fast=True skips full-table counts (used by /api/analytics/bootstrap on Render)."""
    cutoff = _cutoff(days)
    rows = _period_product_rows(db, current_user, cutoff)

    with_sales = [r for r in rows if r.gross_units > 0 or r.net_units > 0]
    top_product = (
        max(with_sales, key=lambda r: (r.net_units, r.net_revenue))
        if with_sales
        else None
    )
    least_product = (
        min(with_sales, key=lambda r: (r.net_units, r.net_revenue))
        if with_sales
        else None
    )

    total_revenue = sum((r.net_revenue for r in rows), Decimal("0"))
    products_sold = sum(1 for r in rows if r.net_units > 0)

    zero_sales_count = None
    total_active_products = None
    if not fast:
        zero_sales_count = (
            tenant_scope.filter_products(db, current_user)
            .filter(
                Product.is_active == True,  # noqa: E712
                ~exists(_recent_sale_exists(cutoff, current_user)),
            )
            .count()
        )
        total_active_products = (
            tenant_scope.filter_products(db, current_user)
            .filter(Product.is_active == True)  # noqa: E712
            .with_entities(func.count(Product.id))
            .scalar()
        )

    return {
        "period_days": days,
        "top_selling": {
            "product_id": top_product.product_id if top_product else None,
            "product_name": top_product.name if top_product else None,
            "barcode": top_product.barcode if top_product else None,
            "quantity_sold": int(top_product.net_units) if top_product else 0,
            "revenue": float(top_product.net_revenue) if top_product else 0.0,
        },
        "least_selling": {
            "product_id": least_product.product_id if least_product else None,
            "product_name": least_product.name if least_product else None,
            "barcode": least_product.barcode if least_product else None,
            "quantity_sold": int(least_product.net_units) if least_product else 0,
            "revenue": float(least_product.net_revenue) if least_product else 0.0,
        },
        "summary": {
            "total_revenue": float(total_revenue),
            "total_products_sold": int(products_sold),
            "total_active_products": total_active_products or 0,
            "zero_sales_count": zero_sales_count or 0,
        },
    }


def fetch_revenue_per_product_rows(
    db: Session, current_user: Any, days: int, limit: int
) -> List[dict]:
    cutoff = _cutoff(days)
    rows = _period_product_rows(db, current_user, cutoff)
    rows.sort(key=lambda r: r.net_revenue, reverse=True)
    out: List[dict] = []
    for r in rows[:limit]:
        if r.gross_units <= 0 and r.refunded_units <= 0:
            continue
        out.append(
            {
                "product_id": r.product_id,
                "product_name": r.name,
                "barcode": r.barcode,
                "total_quantity_sold": int(r.net_units),
                "total_revenue": r.net_revenue,
                "total_profit": r.net_gross_profit,
                "sale_count": int(r.sale_line_count),
            }
        )
    return out


def fetch_zero_sales_rows(
    db: Session, current_user: Any, days: int, limit: int
) -> List[dict]:
    cutoff = _cutoff(days)
    recent_sale = _recent_sale_exists(cutoff, current_user)
    zero_sales_products = (
        tenant_scope.filter_products(db, current_user)
        .filter(
            Product.is_active == True,  # noqa: E712
            ~exists(recent_sale),
        )
        .order_by(Product.name.asc())
        .limit(limit)
        .all()
    )
    if not zero_sales_products:
        return []

    product_ids = [p.id for p in zero_sales_products]
    last_sale_rows = (
        db.query(
            SaleItem.product_id,
            func.max(Sale.created_at).label("last_sale"),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            SaleItem.product_id.in_(product_ids),
            tenant_scope.sale_tenant_match(current_user),
        )
        .group_by(SaleItem.product_id)
        .all()
    )
    last_by_id = {row.product_id: row.last_sale for row in last_sale_rows}

    return [
        {
            "product_id": product.id,
            "product_name": product.name,
            "barcode": product.barcode,
            "stock_qty": product.stock_qty,
            "selling_price": product.selling_price,
            "last_sale_date": last_by_id.get(product.id),
        }
        for product in zero_sales_products
    ]


def build_analytics_bootstrap(
    db: Session,
    current_user: Any,
    days: int = 30,
    revenue_limit: int = 20,
    zero_sales_limit: int = 50,
) -> dict:
    pg_statement_timeout(db)
    zero_sales = fetch_zero_sales_rows(
        db, current_user, days, zero_sales_limit
    )
    dashboard = build_dashboard_summary(db, current_user, days, fast=True)
    zs = len(zero_sales)
    dashboard["summary"]["zero_sales_count"] = (
        zs if zs < zero_sales_limit else f"{zero_sales_limit}+"
    )
    bi_block = _build_bi_health_block(db, current_user, days)

    return {
        "period_days": days,
        "dashboard": dashboard,
        "revenue": fetch_revenue_per_product_rows(
            db, current_user, days, revenue_limit
        ),
        "zero_sales": zero_sales,
        "bi": bi_block,
    }


def _build_bi_health_block(db: Session, current_user: Any, days: int) -> Optional[dict]:
    try:
        from app.bi.ai_client import ai_service_configured
        from app.bi.analytics.engine import build_health_analytics_summary
        from app.bi.scores import compute_health_scores

        analytics = build_health_analytics_summary(db, current_user, days=days)
        scores = compute_health_scores(analytics)
        return {
            "period_days": days,
            "health_scores": scores.model_dump(),
            "ai_service_configured": ai_service_configured(),
            "bi_advisor_available": ai_service_configured(),
        }
    except Exception:
        return None
