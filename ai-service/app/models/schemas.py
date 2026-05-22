"""Request/response schemas for AI microservice."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BIAnalysisRequest(BaseModel):
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None
    analysis_type: str = "business_insights"
    period_days: int = Field(default=30, ge=1, le=365)
    analytics: Dict[str, Any] = Field(default_factory=dict)
    question: Optional[str] = None
    forecast: Optional[Dict[str, Any]] = None


class AdvisorStructured(BaseModel):
    summary: str = ""
    insights: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    action_plan: List[str] = Field(default_factory=list)


class BIAnalysisResponse(BaseModel):
    advisor: str = "DoposAI Business Advisor"
    tenant_id: Optional[int] = None
    analysis_type: str
    structured: AdvisorStructured
    narrative: str = ""
    cached: bool = False
