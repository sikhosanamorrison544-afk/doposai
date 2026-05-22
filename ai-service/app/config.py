"""AI service configuration."""
from __future__ import annotations

import os

API_KEY = os.environ.get("AI_SERVICE_API_KEY", "").strip()
VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://vllm:8000/v1").rstrip("/")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen3-8B")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CACHE_TTL_SECONDS = int(os.environ.get("AI_CACHE_TTL_SECONDS", "1800"))
MAX_TOKENS = int(os.environ.get("AI_MAX_TOKENS", "2048"))
TEMPERATURE = float(os.environ.get("AI_TEMPERATURE", "0.3"))
ADVISOR_NAME = "DoposAI Business Advisor"
