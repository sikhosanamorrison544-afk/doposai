"""DoposAI Business Advisor — prompt assembly + vLLM reasoning."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .. import config
from ..models.schemas import AdvisorStructured, BIAnalysisRequest, BIAnalysisResponse
from . import cache as ai_cache
from .vllm_client import VLLMError, chat_completion, parse_structured_json

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

_PROMPT_FILES = {
    "business_insights": "business_insights.txt",
    "sales_analysis": "sales_analysis.txt",
    "inventory_analysis": "inventory_analysis.txt",
    "profit_analysis": "profit_analysis.txt",
    "forecast_analysis": "forecast_analysis.txt",
}


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return "Analyze the business data and return JSON with summary, insights, risks, recommendations, action_plan."


def _build_user_message(req: BIAnalysisRequest) -> str:
    payload = {
        "tenant_id": req.tenant_id,
        "business_name": req.tenant_name,
        "period_days": req.period_days,
        "analytics": req.analytics,
    }
    if req.forecast:
        payload["forecast"] = req.forecast
    if req.question:
        payload["user_question"] = req.question
    return json.dumps(payload, indent=2, default=str)


def run_analysis(req: BIAnalysisRequest) -> BIAnalysisResponse:
    cached = ai_cache.get(
        req.tenant_id, req.analysis_type, req.analytics, req.question
    )
    if cached:
        cached["cached"] = True
        return BIAnalysisResponse(**cached)

    system = _load_prompt("system_advisor.txt")
    task = _load_prompt(
        _PROMPT_FILES.get(req.analysis_type, "business_insights.txt")
    )
    system_full = f"{system}\n\n---\n\n{task}"

    user_msg = _build_user_message(req)
    try:
        raw = chat_completion(system_full, user_msg)
        parsed = parse_structured_json(raw)
    except VLLMError as e:
        logger.error("vLLM failed: %s", e)
        parsed = {
            "summary": f"{config.ADVISOR_NAME} could not reach the language model. Retry shortly.",
            "insights": ["Analytics were received but AI reasoning is temporarily unavailable."],
            "risks": [],
            "recommendations": ["Check vLLM service health on Contabo."],
            "action_plan": [],
        }
        raw = parsed.get("summary", "")

    structured = AdvisorStructured(
        summary=parsed.get("summary", ""),
        insights=_as_list(parsed.get("insights")),
        risks=_as_list(parsed.get("risks")),
        recommendations=_as_list(parsed.get("recommendations")),
        action_plan=_as_list(parsed.get("action_plan")),
    )
    narrative = parsed.get("summary") or raw
    if req.question and req.question not in narrative:
        narrative = f"Q: {req.question}\n\n{narrative}"

    out = BIAnalysisResponse(
        advisor=config.ADVISOR_NAME,
        tenant_id=req.tenant_id,
        analysis_type=req.analysis_type,
        structured=structured,
        narrative=narrative,
        cached=False,
    )
    ai_cache.set(
        req.tenant_id,
        req.analysis_type,
        req.analytics,
        req.question,
        out.model_dump(),
    )
    return out


def _as_list(val: Any) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x) for x in val]
    return [str(val)]
