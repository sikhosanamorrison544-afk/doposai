"""BI API routes on Render backend — analytics + proxy to Contabo AI service."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import auth
from ..billing.feature_deps import require_feature
from ..billing.features import Feature
from ..database import get_db
from ..models import User
from . import service
from .ai_client import ai_service_configured
from .schemas import BIAdvisorResponse, BIAskRequest, BIAskResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bi", tags=["business-intelligence"])

_bi_analytics = require_feature(Feature.ANALYTICS)
_bi_ai = require_feature(Feature.AI_ASSISTANT)


@router.get("/status")
def bi_status(
    current_user: User = Depends(auth.get_current_active_user),
    _=Depends(_bi_analytics),
):
    return {
        "engine": "DoposAI Business Intelligence",
        "advisor": "DoposAI Business Advisor",
        "ai_service_configured": ai_service_configured(),
        "analytics": "postgresql",
        "llm": "qwen3-vllm-contabo",
    }


@router.get("/health-scores")
def bi_health_scores(
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
    _=Depends(_bi_analytics),
):
    return service.get_health_dashboard(db, current_user, days=days)


@router.post("/business-insights", response_model=BIAdvisorResponse)
def bi_business_insights(
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
    _=Depends(_bi_ai),
):
    return service.run_bi_analysis(
        db, current_user, analysis_type="business_insights", days=days
    )


@router.post("/sales-analysis", response_model=BIAdvisorResponse)
def bi_sales_analysis(
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
    _=Depends(_bi_ai),
):
    return service.run_bi_analysis(
        db, current_user, analysis_type="sales_analysis", days=days
    )


@router.post("/inventory-analysis", response_model=BIAdvisorResponse)
def bi_inventory_analysis(
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
    _=Depends(_bi_ai),
):
    return service.run_bi_analysis(
        db, current_user, analysis_type="inventory_analysis", days=days
    )


@router.post("/profit-analysis", response_model=BIAdvisorResponse)
def bi_profit_analysis(
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
    _=Depends(_bi_ai),
):
    return service.run_bi_analysis(
        db, current_user, analysis_type="profit_analysis", days=days
    )


@router.post("/forecast", response_model=BIAdvisorResponse)
def bi_forecast(
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
    _=Depends(_bi_ai),
):
    return service.run_bi_analysis(
        db, current_user, analysis_type="forecast_analysis", days=days
    )


@router.post("/ask", response_model=BIAskResponse)
def bi_ask(
    body: BIAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
    _=Depends(_bi_ai),
):
    return service.run_ask(db, current_user, body.question, days=body.days)
