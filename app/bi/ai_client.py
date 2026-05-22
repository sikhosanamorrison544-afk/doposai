"""HTTP client to Contabo DoposAI AI microservice (vLLM / Qwen3)."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

AI_SERVICE_URL = os.environ.get("AI_SERVICE_URL", "").rstrip("/")
AI_SERVICE_API_KEY = os.environ.get("AI_SERVICE_API_KEY", "").strip()
AI_SERVICE_TIMEOUT = float(os.environ.get("AI_SERVICE_TIMEOUT_SEC", "120"))


class AIServiceError(Exception):
    pass


def ai_service_configured() -> bool:
    return bool(AI_SERVICE_URL and AI_SERVICE_API_KEY)


def call_ai_endpoint(
    endpoint: str,
    *,
    tenant_id: Optional[int],
    tenant_name: Optional[str],
    analytics: Dict[str, Any],
    question: Optional[str] = None,
    analysis_type: str = "business_insights",
    period_days: int = 30,
    forecast: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not ai_service_configured():
        raise AIServiceError(
            "AI service not configured. Set AI_SERVICE_URL and AI_SERVICE_API_KEY."
        )

    path = endpoint if endpoint.startswith("/") else f"/ai/{endpoint}"
    url = f"{AI_SERVICE_URL}{path}"
    body = {
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "analysis_type": analysis_type,
        "period_days": period_days,
        "analytics": analytics,
        "question": question,
        "forecast": forecast,
    }
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": AI_SERVICE_API_KEY,
    }
    try:
        with httpx.Client(timeout=AI_SERVICE_TIMEOUT) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("AI service HTTP %s: %s", e.response.status_code, e.response.text[:500])
        raise AIServiceError(f"AI service error: {e.response.status_code}") from e
    except httpx.RequestError as e:
        logger.error("AI service unreachable: %s", e)
        raise AIServiceError("AI service unreachable") from e
