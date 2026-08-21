"""Profitability aggregates for BI."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import tenant_scope
from ...finance_service import (
    approved_expenses_total,
    approved_refunds_total,
    product_period_metrics,
    refund_aware_gross_profit,
    refund_gross_profit_reversal,
    unit_cost_expr,
)
from ...models import Product, Sale, SaleItem, User


def profit_metrics(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    prev_start: datetime,
    prev_end: datetime,
) -> Dict[str, Any]:
    def _profit(s: datetime, e: datetime) -> Dict[str, float]:
        # BI windows are half-open [s, e); finance helpers use closed end.
        end_closed = e - timedelta(microseconds=1) if e > s else e
        revenue_gross = float(
            db.query(func.coalesce(func.sum(SaleItem.line_total), 0))
            .join(Sale, SaleItem.sale_id == Sale.id)
            .filter(
                Sale.created_at >= s,
                Sale.created_at < e,
                tenant_scope.sale_tenant_match(user),
            )
            .scalar()
            or 0
        )
        cogs_gross = float(
            db.query(
                func.coalesce(
                    func.sum(SaleItem.quantity * unit_cost_expr()),
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
            or 0
        )
        refunds = float(approved_refunds_total(db, user, s, end_closed, branch_id=None))
        # Margin reversed on refunds ≈ revenue reverse − remaining COGS reverse
        gp = float(refund_aware_gross_profit(db, user, s, end_closed, branch_id=None))
        gp_reversal = float(
            refund_gross_profit_reversal(db, user, s, end_closed, branch_id=None)
        )
        # refund COGS ≈ refund revenue − margin reversal (may exceed gross COGS
        # in a refund-only window — negative net COGS is valid).
        refund_cogs = refunds - gp_reversal
        rev = revenue_gross - refunds
        cost = cogs_gross - refund_cogs
        return {
            "revenue": round(rev, 2),
            "cogs": round(cost, 2),
            "gross_profit": round(gp, 2),
            "gross_margin_percent": round(gp / rev * 100, 2) if rev > 0 else 0.0,
        }

    current = _profit(start, end)
    previous = _profit(prev_start, prev_end)
    end_closed = end - timedelta(microseconds=1) if end > start else end
    expenses_f = float(
        approved_expenses_total(db, user, start, end_closed, branch_id=None)
    )

    margin_products = _margin_leaders(db, user, start, end)

    return {
        "revenue_this_period": current["revenue"],
        "gross_profit_this_period": current["gross_profit"],
        "gross_margin_percent": current["gross_margin_percent"],
        "gross_profit_last_period": previous["gross_profit"],
        "profit_change_percent": _pct_change(
            current["gross_profit"], previous["gross_profit"]
        ),
        "operating_expenses": expenses_f,
        "operating_expenses_withdrawals": expenses_f,  # legacy alias → approved expenses
        "estimated_net_after_expenses": round(current["gross_profit"] - expenses_f, 2),
        "highest_margin_products": margin_products["high"],
        "lowest_margin_products": margin_products["low"],
    }


def _margin_leaders(
    db: Session, user: User, start: datetime, end: datetime
) -> Dict[str, List[Dict[str, Any]]]:
    rows = product_period_metrics(
        db, user, start, end, end_exclusive=True, active_only=True
    )
    scored: List[Dict[str, Any]] = []
    for r in rows:
        rev = float(r.net_revenue)
        if rev <= 0:
            continue
        cost = float(r.net_cogs)
        gp = float(r.net_gross_profit)
        margin_pct = round(gp / rev * 100, 1) if rev > 0 else 0.0
        scored.append(
            {
                "product_id": r.product_id,
                "name": r.name,
                "revenue": rev,
                "margin_percent": margin_pct,
                "gross_profit": round(gp, 2),
            }
        )
    scored.sort(key=lambda x: x["margin_percent"], reverse=True)
    return {"high": scored[:8], "low": list(reversed(scored[-8:]))}


def _pct_change(current: float, previous: float) -> float:
    if previous <= 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 2)
