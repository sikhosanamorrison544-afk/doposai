"""AI API routes — tenant-aware via request body (Render sends pre-scoped analytics)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..models.schemas import BIAnalysisRequest, BIAnalysisResponse
from ..services.advisor import run_analysis
from .deps import verify_api_key

router = APIRouter(prefix="/ai", tags=["ai"])


def _handle(req: BIAnalysisRequest, analysis_type: str) -> BIAnalysisResponse:
    req.analysis_type = analysis_type
    return run_analysis(req)


@router.get("/health")
def health():
    return {"status": "ok", "service": "doposai-ai", "advisor": "DoposAI Business Advisor"}


@router.post("/business-insights", response_model=BIAnalysisResponse)
def business_insights(
    req: BIAnalysisRequest,
    _: str = Depends(verify_api_key),
):
    return _handle(req, "business_insights")


@router.post("/sales-analysis", response_model=BIAnalysisResponse)
def sales_analysis(req: BIAnalysisRequest, _: str = Depends(verify_api_key)):
    return _handle(req, "sales_analysis")


@router.post("/inventory-analysis", response_model=BIAnalysisResponse)
def inventory_analysis(req: BIAnalysisRequest, _: str = Depends(verify_api_key)):
    return _handle(req, "inventory_analysis")


@router.post("/profit-analysis", response_model=BIAnalysisResponse)
def profit_analysis(req: BIAnalysisRequest, _: str = Depends(verify_api_key)):
    return _handle(req, "profit_analysis")


@router.post("/forecast", response_model=BIAnalysisResponse)
def forecast(req: BIAnalysisRequest, _: str = Depends(verify_api_key)):
    return _handle(req, "forecast_analysis")


@router.post("/ask", response_model=BIAnalysisResponse)
def ask(req: BIAnalysisRequest, _: str = Depends(verify_api_key)):
    if not req.question:
        raise HTTPException(status_code=400, detail="question is required")
    # Intent-specific prompt selection can be added in Phase 2
    req.analysis_type = req.analysis_type or "business_insights"
    return run_analysis(req)
