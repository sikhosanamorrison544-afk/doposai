"""Analytics page queries — one round-trip, bounded work, Postgres statement timeout."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, List, Optional

from sqlalchemy import and_, exists, func, select, text
from sqlalchemy.orm import Session

from app import tenant_scope
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


def _product_sales_agg(db: Session, current_user: Any, cutoff: datetime):
    return (
        db.query(
            Product.id,
            Product.name,
            Product.barcode,
            func.sum(SaleItem.quantity).label("total_quantity"),
            func.sum(SaleItem.line_total).label("total_revenue"),
            func.sum(
                SaleItem.line_total - (SaleItem.quantity * Product.cost_price)
            ).label("total_profit"),
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(Sale.created_at >= cutoff)
        .filter(
            and_(
                tenant_scope.sale_tenant_match(current_user),
                tenant_scope.product_tenant_match(current_user),
            )
        )
        .filter(Product.is_active == True)  # noqa: E712
        .group_by(Product.id, Product.name, Product.barcode)
    )


def build_dashboard_summary(
    db: Session, current_user: Any, days: int, *, fast: bool = False
) -> dict:
    """fast=True skips full-table counts (used by /api/analytics/bootstrap on Render)."""
    cutoff = _cutoff(days)
    sale_filters = and_(
        Sale.created_at >= cutoff,
        tenant_scope.sale_tenant_match(current_user),
    )

    totals = (
        db.query(
            func.coalesce(func.sum(SaleItem.line_total), 0).label("total_revenue"),
            func.count(func.distinct(SaleItem.product_id)).label("products_sold"),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(sale_filters)
        .first()
    )

    agg = _product_sales_agg(db, current_user, cutoff)
    top_product = agg.order_by(func.sum(SaleItem.quantity).desc()).first()
    least_product = agg.order_by(func.sum(SaleItem.quantity).asc()).first()

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
            "product_id": top_product.id if top_product else None,
            "product_name": top_product.name if top_product else None,
            "barcode": top_product.barcode if top_product else None,
            "quantity_sold": int(top_product.total_quantity or 0) if top_product else 0,
            "revenue": float(top_product.total_revenue or 0) if top_product else 0.0,
        },
        "least_selling": {
            "product_id": least_product.id if least_product else None,
            "product_name": least_product.name if least_product else None,
            "barcode": least_product.barcode if least_product else None,
            "quantity_sold": int(least_product.total_quantity or 0) if least_product else 0,
            "revenue": float(least_product.total_revenue or 0) if least_product else 0.0,
        },
        "summary": {
            "total_revenue": float(totals.total_revenue or 0) if totals else 0.0,
            "total_products_sold": int(totals.products_sold or 0) if totals else 0,
            "total_active_products": total_active_products or 0,
            "zero_sales_count": zero_sales_count or 0,
        },
    }


def fetch_revenue_per_product_rows(
    db: Session, current_user: Any, days: int, limit: int
) -> List[dict]:
    cutoff = _cutoff(days)
    results = (
        db.query(
            Product.id,
            Product.name,
            Product.barcode,
            func.sum(SaleItem.quantity).label("total_quantity"),
            func.sum(SaleItem.line_total).label("total_revenue"),
            func.sum(
                SaleItem.line_total - (SaleItem.quantity * Product.cost_price)
            ).label("total_profit"),
            func.count(SaleItem.id).label("sale_count"),
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(Sale.created_at >= cutoff)
        .filter(
            and_(
                tenant_scope.sale_tenant_match(current_user),
                tenant_scope.product_tenant_match(current_user),
            )
        )
        .filter(Product.is_active == True)  # noqa: E712
        .group_by(Product.id, Product.name, Product.barcode)
        .order_by(func.sum(SaleItem.line_total).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "product_id": r.id,
            "product_name": r.name,
            "barcode": r.barcode,
            "total_quantity_sold": int(r.total_quantity or 0),
            "total_revenue": Decimal(str(r.total_revenue or 0)),
            "total_profit": Decimal(str(r.total_profit or 0)),
            "sale_count": int(r.sale_count or 0),
        }
        for r in results
    ]


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


def _build_bi_health_block(db: Session, current_user: Any, days: int) -> dict | None:
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
