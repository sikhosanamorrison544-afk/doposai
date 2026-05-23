"""Inventory aggregates for BI."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from ... import tenant_scope
from ...models import Product, Sale, SaleItem, User


def inventory_metrics_for_health(db: Session, user: User) -> Dict[str, Any]:
    """Stock signals for health scores only (skips dead-stock scan and turnover)."""
    products_q = tenant_scope.filter_products(db, user).filter(Product.is_active == True)  # noqa: E712

    low_stock = (
        products_q.filter(
            Product.stock_qty <= func.coalesce(Product.low_stock_threshold, 5)
        )
        .order_by(Product.stock_qty.asc())
        .limit(20)
        .all()
    )
    out_of_stock = products_q.filter(Product.stock_qty <= 0).limit(20).all()

    return {
        "total_active_skus": int(products_q.count()),
        "low_stock_products": [_product_row(p) for p in low_stock],
        "out_of_stock_products": [_product_row(p) for p in out_of_stock],
    }


def inventory_metrics(db: Session, user: User) -> Dict[str, Any]:
    products_q = tenant_scope.filter_products(db, user).filter(Product.is_active == True)  # noqa: E712

    total_skus = products_q.count()
    stock_value = (
        products_q.with_entities(
            func.coalesce(
                func.sum(Product.stock_qty * Product.cost_price),
                0,
            )
        ).scalar()
        or 0
    )

    low_stock = (
        products_q.filter(
            Product.stock_qty <= func.coalesce(Product.low_stock_threshold, 5)
        )
        .order_by(Product.stock_qty.asc())
        .limit(20)
        .all()
    )

    out_of_stock = (
        products_q.filter(Product.stock_qty <= 0).limit(20).all()
    )

    cutoff = datetime.utcnow() - timedelta(days=90)
    recent_sale = (
        select(1)
        .select_from(SaleItem)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .where(
            SaleItem.product_id == Product.id,
            Sale.created_at >= cutoff,
            tenant_scope.sale_tenant_match(user),
        )
    )
    dead_stock = products_q.filter(~exists(recent_sale)).limit(15).all()

    turnover = _inventory_turnover(db, user, days=30)

    return {
        "total_active_skus": int(total_skus),
        "inventory_value_at_cost": float(stock_value),
        "inventory_turnover_ratio": turnover,
        "low_stock_products": [_product_row(p) for p in low_stock],
        "out_of_stock_products": [_product_row(p) for p in out_of_stock],
        "dead_stock_candidates": [_product_row(p) for p in dead_stock],
    }


def _product_row(p: Product) -> Dict[str, Any]:
    cost = float(p.cost_price or 0)
    price = float(p.selling_price or 0)
    margin = round((price - cost) / price * 100, 1) if price > 0 else 0.0
    return {
        "product_id": p.id,
        "name": p.name,
        "barcode": p.barcode,
        "stock_qty": float(p.stock_qty or 0),
        "cost_price": cost,
        "selling_price": price,
        "margin_percent": margin,
    }


def _inventory_turnover(db: Session, user: User, days: int) -> float:
    """Approximate turnover: COGS / average inventory value."""
    from datetime import datetime, timedelta

    start = datetime.utcnow() - timedelta(days=days)
    cogs = (
        db.query(
            func.coalesce(
                func.sum(SaleItem.quantity * Product.cost_price),
                0,
            )
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .join(Product, SaleItem.product_id == Product.id)
        .filter(
            Sale.created_at >= start,
            tenant_scope.sale_tenant_match(user),
            tenant_scope.product_tenant_match(user),
        )
        .scalar()
        or 0
    )
    inv_val = (
        tenant_scope.filter_products(db, user)
        .filter(Product.is_active == True)  # noqa: E712
        .with_entities(func.coalesce(func.sum(Product.stock_qty * Product.cost_price), 0))
        .scalar()
        or 1
    )
    return round(float(cogs) / max(float(inv_val), 1.0), 2)
