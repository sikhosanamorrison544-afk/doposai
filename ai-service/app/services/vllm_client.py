"""vLLM OpenAI-compatible client (Qwen3). No Ollama."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

from .. import config

logger = logging.getLogger(__name__)


class VLLMError(Exception):
    pass


def chat_completion(
    system: str,
    user: str,
    *,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> str:
    url = f"{config.VLLM_BASE_URL}/chat/completions"
    payload = {
        "model": config.VLLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens or config.MAX_TOKENS,
        "temperature": temperature if temperature is not None else config.TEMPERATURE,
    }
    try:
        with httpx.Client(timeout=180.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        logger.error("vLLM HTTP %s: %s", e.response.status_code, e.response.text[:800])
        raise VLLMError(f"vLLM error {e.response.status_code}") from e
    except Exception as e:
        raise VLLMError(str(e)) from e


def parse_structured_json(text: str) -> Dict[str, Any]:
    """Extract JSON object from model output."""
    text = (text or "").strip()
    if not text:
        return {}
    # Strip markdown fences
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
        if m:
            text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find first { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {
        "summary": text[:2000],
        "insights": [],
        "risks": [],
        "recommendations": [],
        "action_plan": [],
    }
