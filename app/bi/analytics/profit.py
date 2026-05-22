"""Profitability aggregates for BI."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import tenant_scope
from ...models import Product, Sale, SaleItem, User, Withdrawal


def profit_metrics(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    prev_start: datetime,
    prev_end: datetime,
) -> Dict[str, Any]:
    def _profit(s: datetime, e: datetime) -> Dict[str, float]:
        revenue = (
            db.query(func.coalesce(func.sum(SaleItem.line_total), 0))
            .join(Sale, SaleItem.sale_id == Sale.id)
            .filter(
                Sale.created_at >= s,
                Sale.created_at < e,
                tenant_scope.sale_tenant_match(user),
            )
            .scalar()
        )
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
                Sale.created_at >= s,
                Sale.created_at < e,
                tenant_scope.sale_tenant_match(user),
                tenant_scope.product_tenant_match(user),
            )
            .scalar()
        )
        rev = float(revenue or 0)
        cost = float(cogs or 0)
        return {
            "revenue": rev,
            "cogs": cost,
            "gross_profit": round(rev - cost, 2),
            "gross_margin_percent": round((rev - cost) / rev * 100, 2) if rev > 0 else 0.0,
        }

    current = _profit(start, end)
    previous = _profit(prev_start, prev_end)
    expenses = (
        db.query(func.coalesce(func.sum(Withdrawal.amount), 0))
        .filter(
            Withdrawal.created_at >= start,
            Withdrawal.created_at < end,
            tenant_scope.withdrawal_tenant_match(user),
        )
        .scalar()
    )
    expenses_f = float(expenses or 0)

    margin_products = _margin_leaders(db, user, start, end)

    return {
        "revenue_this_period": current["revenue"],
        "gross_profit_this_period": current["gross_profit"],
        "gross_margin_percent": current["gross_margin_percent"],
        "gross_profit_last_period": previous["gross_profit"],
        "profit_change_percent": _pct_change(
            current["gross_profit"], previous["gross_profit"]
        ),
        "operating_expenses_withdrawals": expenses_f,
        "estimated_net_after_expenses": round(current["gross_profit"] - expenses_f, 2),
        "highest_margin_products": margin_products["high"],
        "lowest_margin_products": margin_products["low"],
    }


def _margin_leaders(
    db: Session, user: User, start: datetime, end: datetime
) -> Dict[str, List[Dict[str, Any]]]:
    rows = (
        db.query(
            Product.id,
            Product.name,
            func.sum(SaleItem.line_total).label("revenue"),
            func.sum(SaleItem.quantity * Product.cost_price).label("cost"),
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
        .group_by(Product.id, Product.name)
        .having(func.sum(SaleItem.line_total) > 0)
        .all()
    )
    scored: List[Dict[str, Any]] = []
    for r in rows:
        rev = float(r.revenue or 0)
        cost = float(r.cost or 0)
        margin_pct = round((rev - cost) / rev * 100, 1) if rev > 0 else 0.0
        scored.append(
            {
                "product_id": r.id,
                "name": r.name,
                "revenue": rev,
                "margin_percent": margin_pct,
                "gross_profit": round(rev - cost, 2),
            }
        )
    scored.sort(key=lambda x: x["margin_percent"], reverse=True)
    return {"high": scored[:8], "low": list(reversed(scored[-8:]))}


def _pct_change(current: float, previous: float) -> float:
    if previous <= 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 2)
