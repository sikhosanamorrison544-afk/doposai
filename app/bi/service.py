"""Orchestrates analytics, forecasting, cache, and AI service calls."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..models import User
from . import cache
from .ai_client import AIServiceError, ai_service_configured, call_ai_endpoint
from .analytics import build_health_analytics_summary, build_tenant_analytics_summary
from .forecasting import build_forecasts
from .intent import detect_intent
from .scores import compute_health_scores
from .schemas import AdvisorSection, BIAdvisorResponse, BIAskResponse, HealthScores

logger = logging.getLogger(__name__)

_ANALYSIS_TYPES = {
    "business_insights": "business_insights",
    "sales": "sales_analysis",
    "inventory": "inventory_analysis",
    "profit": "profit_analysis",
    "forecast": "forecast_analysis",
}


def _tenant_id(user: User) -> Optional[int]:
    from .. import tenant_scope

    return tenant_scope.tenant_id_for_row(user)


def _fallback_advisor(
    analysis_type: str,
    analytics: Dict[str, Any],
    *,
    question: Optional[str] = None,
) -> AdvisorSection:
    """Rule-based advisor when AI service is offline."""
    rev_chg = analytics.get("revenue_change_percent", 0)
    insights = [
        f"Revenue this period: {analytics.get('revenue_this_period') or analytics.get('sales_this_period', 0)}",
        f"Revenue change vs prior period: {rev_chg}%",
    ]
    risks = []
    if rev_chg < -10:
        risks.append("Revenue declined more than 10% — review pricing, staffing, and top sellers.")
    if analytics.get("out_of_stock_products"):
        risks.append(f"{len(analytics['out_of_stock_products'])} products are out of stock.")
    if float(analytics.get("total_outstanding_debt", 0)) > 0:
        risks.append(
            f"Outstanding debt total: {analytics['total_outstanding_debt']} — impacts cash flow."
        )
    recs = []
    if analytics.get("low_stock_products"):
        recs.append("Prioritize restocking low-stock items with high sales velocity.")
    if analytics.get("top_products"):
        top = analytics["top_products"][0]
        recs.append(f"Promote top seller: {top.get('name')} (revenue {top.get('revenue')}).")
    if question:
        insights.insert(0, f"Question: {question}")
    return AdvisorSection(
        summary=f"DoposAI offline summary ({analysis_type}). Connect AI_SERVICE_URL for full Qwen3 analysis.",
        insights=insights,
        risks=risks or ["No critical risks flagged by rules engine."],
        recommendations=recs or ["Maintain current operations and monitor weekly trends."],
        action_plan=[
            "Review dashboard health scores",
            "Restock critical SKUs",
            "Follow up on outstanding credit and layby balances",
        ],
    )


def _parse_ai_response(data: Dict[str, Any]) -> tuple[AdvisorSection, str]:
    structured = data.get("structured") or {}
    if isinstance(structured, dict):
        section = AdvisorSection(
            summary=structured.get("summary", ""),
            insights=structured.get("insights") or [],
            risks=structured.get("risks") or [],
            recommendations=structured.get("recommendations") or [],
            action_plan=structured.get("action_plan") or [],
        )
    else:
        section = AdvisorSection()
    return section, data.get("narrative", section.summary)


def run_bi_analysis(
    db: Session,
    user: User,
    *,
    analysis_type: str = "business_insights",
    days: int = 30,
    question: Optional[str] = None,
    use_cache: bool = True,
) -> BIAdvisorResponse:
    tid = _tenant_id(user)
    cache_payload = {"type": analysis_type, "days": days, "q": question or ""}
    if use_cache:
        hit = cache.get_cached(tid, "advisor", cache_payload)
        if hit:
            hit["cached"] = True
            return BIAdvisorResponse(**hit)

    analytics = build_tenant_analytics_summary(db, user, days=days)
    forecast = None
    if analysis_type in ("forecast", "business_insights", "forecast_analysis"):
        forecast = build_forecasts(db, user, analytics, horizon_days=14)

    health = compute_health_scores(analytics)
    ai_type = analysis_type.replace("-", "_")
    if ai_type not in _ANALYSIS_TYPES.values():
        ai_type = _ANALYSIS_TYPES.get(analysis_type, "business_insights")

    path_map = {
        "business_insights": "business-insights",
        "sales_analysis": "sales-analysis",
        "inventory_analysis": "inventory-analysis",
        "profit_analysis": "profit-analysis",
        "forecast_analysis": "forecast",
    }
    path = path_map.get(ai_type, "business-insights")

    structured = _fallback_advisor(ai_type, analytics, question=question)
    narrative = structured.summary
    cached_ai = False

    if ai_service_configured():
        try:
            ai_data = call_ai_endpoint(
                path,
                tenant_id=tid,
                tenant_name=analytics.get("business_name"),
                analytics=_slim_snapshot(analytics),
                question=question,
                analysis_type=ai_type,
                period_days=days,
                forecast=forecast,
            )
            structured, narrative = _parse_ai_response(ai_data)
            cached_ai = ai_data.get("cached", False)
        except AIServiceError as e:
            logger.warning("AI service call failed, using fallback: %s", e)
    else:
        logger.info("AI service not configured; using rule-based advisor")

    out = BIAdvisorResponse(
        tenant_id=tid,
        analysis_type=ai_type,
        period_days=days,
        analytics_snapshot=_slim_snapshot(analytics),
        forecast=forecast,
        health_scores=health,
        structured=structured,
        narrative=narrative,
        cached=cached_ai,
    )
    if use_cache:
        cache.set_cached(tid, "advisor", cache_payload, out.model_dump())
    return out


def run_ask(
    db: Session,
    user: User,
    question: str,
    *,
    days: int = 30,
) -> BIAskResponse:
    intent = detect_intent(question)
    type_map = {
        "sales": "sales_analysis",
        "inventory": "inventory_analysis",
        "profit": "profit_analysis",
        "forecast": "forecast_analysis",
        "debt": "business_insights",
        "general": "business_insights",
    }
    base = run_bi_analysis(
        db,
        user,
        analysis_type=type_map.get(intent, "business_insights"),
        days=days,
        question=question,
    )
    return BIAskResponse(
        **base.model_dump(),
        detected_intent=intent,
        question=question,
    )


def get_health_dashboard(
    db: Session,
    user: User,
    *,
    days: int = 30,
) -> Dict[str, Any]:
    tid = _tenant_id(user)
    cache_payload = {"days": days}
    hit = cache.get_cached(tid, "health", cache_payload)
    if hit and isinstance(hit.get("health_scores"), dict):
        return hit

    analytics = build_health_analytics_summary(db, user, days=days)
    scores = compute_health_scores(analytics)
    payload = {
        "tenant_id": tid,
        "period_days": days,
        "health_scores": scores.model_dump(),
        "ai_service_configured": ai_service_configured(),
        "bi_advisor_available": ai_service_configured(),
    }
    cache.set_cached(tid, "health", cache_payload, payload, ttl=900)
    return payload


def _slim_snapshot(analytics: Dict[str, Any]) -> Dict[str, Any]:
    """Smaller payload for API responses (omit huge daily series)."""
    slim = dict(analytics)
    daily = slim.get("daily_revenue") or []
    if len(daily) > 14:
        slim["daily_revenue"] = daily[-14:]
    return slim
