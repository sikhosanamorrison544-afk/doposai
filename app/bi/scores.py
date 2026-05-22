"""Dashboard health scores (green / yellow / red)."""
from __future__ import annotations

from typing import Any, Dict

from .schemas import HealthScores


def compute_health_scores(analytics: Dict[str, Any]) -> HealthScores:
    rev_change = float(analytics.get("revenue_change_percent") or 0)
    margin = float(analytics.get("gross_margin_percent") or 0)
    low_stock = len(analytics.get("low_stock_products") or [])
    out_stock = len(analytics.get("out_of_stock_products") or [])
    debt = float(analytics.get("total_outstanding_debt") or 0)
    revenue = float(analytics.get("revenue_this_period") or 0)

    sales_score = _score_sales_trend(rev_change)
    inv_score = _score_inventory_risk(low_stock, out_stock)
    profit_score = _score_profitability(margin, analytics)
    health_score = round((sales_score + inv_score + profit_score) / 3, 1)

    return HealthScores(
        business_health=_color(health_score),
        sales_trend=_color(sales_score),
        inventory_risk=_color(inv_score, invert=True),
        profitability=_color(profit_score),
        business_health_score=health_score,
        sales_trend_score=sales_score,
        inventory_risk_score=inv_score,
        profitability_score=profit_score,
    )


def _score_sales_trend(rev_change_pct: float) -> float:
    if rev_change_pct >= 10:
        return 90.0
    if rev_change_pct >= 0:
        return 70.0
    if rev_change_pct >= -10:
        return 50.0
    if rev_change_pct >= -25:
        return 30.0
    return 15.0


def _score_inventory_risk(low: int, out: int) -> float:
    penalty = low * 3 + out * 8
    return max(10.0, 100.0 - min(penalty, 90))


def _score_profitability(margin_pct: float, analytics: Dict[str, Any]) -> float:
    profit_chg = float(analytics.get("profit_change_percent") or 0)
    base = min(100.0, margin_pct * 2.5) if margin_pct > 0 else 40.0
    if profit_chg < -15:
        base -= 20
    elif profit_chg > 10:
        base += 10
    return max(10.0, min(100.0, base))


def _color(score: float, *, invert: bool = False) -> str:
    effective = 100 - score if invert else score
    if effective >= 70:
        return "green"
    if effective >= 45:
        return "yellow"
    return "red"
