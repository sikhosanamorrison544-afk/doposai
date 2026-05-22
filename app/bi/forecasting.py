"""
Statistical forecasting (not LLM) — revenue, sales volume, stockout risk, reorder hints.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import tenant_scope
from ..models import Product, Sale, SaleItem, User


def build_forecasts(
    db: Session,
    user: User,
    analytics: Dict[str, Any],
    *,
    horizon_days: int = 14,
) -> Dict[str, Any]:
    daily = analytics.get("daily_revenue") or []
    revenues = [float(d.get("revenue", 0)) for d in daily]

    revenue_forecast = _linear_forecast(revenues, horizon_days)
    sales_forecast = _linear_forecast(
        [float(d.get("transactions", 0)) for d in daily], horizon_days
    )

    stockout = _stockout_predictions(db, user)
    reorder = _reorder_suggestions(db, user, analytics)

    return {
        "horizon_days": horizon_days,
        "method": "linear_trend_on_daily_series",
        "revenue_forecast": revenue_forecast,
        "sales_volume_forecast": sales_forecast,
        "projected_revenue_next_period": revenue_forecast.get("total_projected", 0),
        "stockout_predictions": stockout,
        "reorder_suggestions": reorder,
    }


def _linear_forecast(series: List[float], horizon: int) -> Dict[str, Any]:
    n = len(series)
    if n < 3:
        avg = sum(series) / max(n, 1) if series else 0.0
        projected = [round(avg, 2)] * horizon
        return {
            "daily_projected": projected,
            "total_projected": round(sum(projected), 2),
            "trend": "insufficient_data",
            "confidence": "low",
        }

    # Simple least-squares slope on indices 0..n-1
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(series) / n
    num = sum((xs[i] - mean_x) * (series[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n)) or 1.0
    slope = num / den
    intercept = mean_y - slope * mean_x

    projected = []
    for i in range(n, n + horizon):
        val = max(0.0, intercept + slope * i)
        projected.append(round(val, 2))

    trend = "up" if slope > 0.05 else "down" if slope < -0.05 else "flat"
    return {
        "daily_projected": projected,
        "total_projected": round(sum(projected), 2),
        "trend": trend,
        "slope_per_day": round(slope, 4),
        "confidence": "medium" if n >= 14 else "low",
    }


def _stockout_predictions(db: Session, user: User, *, limit: int = 15) -> List[Dict[str, Any]]:
    """Products likely to run out based on recent velocity vs stock."""
    cutoff = datetime.utcnow() - timedelta(days=14)
    velocity = (
        db.query(
            Product.id,
            Product.name,
            Product.stock_qty,
            func.sum(SaleItem.quantity).label("sold"),
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.created_at >= cutoff,
            Product.is_active == True,  # noqa: E712
            tenant_scope.sale_tenant_match(user),
            tenant_scope.product_tenant_match(user),
        )
        .group_by(Product.id, Product.name, Product.stock_qty)
        .all()
    )
    out: List[Dict[str, Any]] = []
    for r in velocity:
        sold = float(r.sold or 0)
        if sold <= 0:
            continue
        daily_rate = sold / 14.0
        stock = float(r.stock_qty or 0)
        if daily_rate <= 0:
            continue
        days_left = stock / daily_rate
        if days_left <= 14:
            out.append(
                {
                    "product_id": r.id,
                    "name": r.name,
                    "stock_qty": stock,
                    "avg_daily_sales": round(daily_rate, 2),
                    "estimated_days_until_stockout": round(days_left, 1),
                    "risk": "high" if days_left <= 7 else "medium",
                }
            )
    out.sort(key=lambda x: x["estimated_days_until_stockout"])
    return out[:limit]


def _reorder_suggestions(
    db: Session, user: User, analytics: Dict[str, Any], *, limit: int = 20
) -> List[Dict[str, Any]]:
    low = analytics.get("low_stock_products") or []
    stockout = _stockout_predictions(db, user, limit=limit)
    by_id: Dict[int, Dict[str, Any]] = {}
    for item in low:
        pid = item.get("product_id")
        if pid:
            by_id[pid] = {
                "product_id": pid,
                "name": item.get("name"),
                "current_stock": item.get("stock_qty"),
                "reason": "below_low_stock_threshold",
                "suggested_action": "reorder",
            }
    for item in stockout:
        pid = item.get("product_id")
        if pid and pid not in by_id:
            by_id[pid] = {
                "product_id": pid,
                "name": item.get("name"),
                "current_stock": item.get("stock_qty"),
                "reason": "high_velocity_stockout_risk",
                "suggested_action": "urgent_reorder",
                "estimated_days_until_stockout": item.get("estimated_days_until_stockout"),
            }
    return list(by_id.values())[:limit]
