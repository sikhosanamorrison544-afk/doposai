"""Redis cache for AI responses."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from .. import config

logger = logging.getLogger(__name__)
_client = None
_tried = False


def _redis():
    global _client, _tried
    if _tried:
        return _client
    _tried = True
    try:
        import redis

        _client = redis.from_url(config.REDIS_URL, decode_responses=True)
        _client.ping()
    except Exception as e:
        logger.warning("Redis cache disabled: %s", e)
        _client = None
    return _client


def cache_key(tenant_id: Optional[int], analysis_type: str, analytics: dict, question: Optional[str]) -> str:
    raw = json.dumps(
        {"tid": tenant_id, "t": analysis_type, "q": question, "h": _hash_analytics(analytics)},
        sort_keys=True,
    )
    return f"doposai:ai:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def _hash_analytics(analytics: dict) -> str:
    # Stable hash on key metrics only (ignore timestamps)
    keys = (
        "sales_this_period",
        "revenue_change_percent",
        "gross_margin_percent",
        "total_outstanding_debt",
        "total_active_skus",
    )
    slim = {k: analytics.get(k) for k in keys if k in analytics}
    return hashlib.md5(json.dumps(slim, sort_keys=True, default=str).encode()).hexdigest()


def get(tenant_id: Optional[int], analysis_type: str, analytics: dict, question: Optional[str]) -> Optional[dict]:
    r = _redis()
    if not r:
        return None
    try:
        val = r.get(cache_key(tenant_id, analysis_type, analytics, question))
        return json.loads(val) if val else None
    except Exception:
        return None


def set(
    tenant_id: Optional[int],
    analysis_type: str,
    analytics: dict,
    question: Optional[str],
    value: dict,
    ttl: Optional[int] = None,
) -> None:
    r = _redis()
    if not r:
        return
    try:
        r.setex(
            cache_key(tenant_id, analysis_type, analytics, question),
            ttl or config.CACHE_TTL_SECONDS,
            json.dumps(value, default=str),
        )
    except Exception as e:
        logger.debug("Cache set failed: %s", e)
