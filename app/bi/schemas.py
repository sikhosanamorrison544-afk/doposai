"""Pydantic models for BI API requests and structured advisor responses."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class BIAskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    days: int = Field(default=30, ge=7, le=365)


class BIDaysQuery(BaseModel):
    days: int = Field(default=30, ge=7, le=365)


class HealthScores(BaseModel):
    business_health: Literal["green", "yellow", "red"]
    sales_trend: Literal["green", "yellow", "red"]
    inventory_risk: Literal["green", "yellow", "red"]
    profitability: Literal["green", "yellow", "red"]
    business_health_score: float = Field(ge=0, le=100)
    sales_trend_score: float = Field(ge=0, le=100)
    inventory_risk_score: float = Field(ge=0, le=100)
    profitability_score: float = Field(ge=0, le=100)


class AdvisorSection(BaseModel):
    summary: str = ""
    insights: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    action_plan: List[str] = Field(default_factory=list)


class BIAdvisorResponse(BaseModel):
    advisor: str = "DoposAI Business Advisor"
    tenant_id: Optional[int] = None
    analysis_type: str
    period_days: int
    analytics_snapshot: Dict[str, Any] = Field(default_factory=dict)
    forecast: Optional[Dict[str, Any]] = None
    health_scores: Optional[HealthScores] = None
    structured: AdvisorSection
    narrative: str = ""
    cached: bool = False


class BIAskResponse(BIAdvisorResponse):
    detected_intent: str = "general"
    question: str = ""
