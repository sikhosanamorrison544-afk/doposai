"""BI response cache — in-memory with optional Redis."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MEMORY: dict[str, tuple[float, Any]] = {}
_DEFAULT_TTL = int(os.environ.get("BI_CACHE_TTL_SECONDS", "1800"))  # 30 min
_redis_client = None
_redis_tried = False


def _redis():
    global _redis_client, _redis_tried
    if _redis_tried:
        return _redis_client
    _redis_tried = True
    url = os.environ.get("BI_REDIS_URL", os.environ.get("REDIS_URL", "")).strip()
    if not url:
        return None
    try:
        import redis

        _redis_client = redis.from_url(url, decode_responses=True)
        _redis_client.ping()
        logger.info("BI cache using Redis")
    except Exception as e:
        logger.warning("BI Redis unavailable, using memory cache: %s", e)
        _redis_client = None
    return _redis_client


def _cache_key(tenant_id: Optional[int], namespace: str, payload: dict) -> str:
    raw = json.dumps({"tid": tenant_id, "ns": namespace, "p": payload}, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return f"bi:{tenant_id or 'legacy'}:{namespace}:{digest}"


def get_cached(tenant_id: Optional[int], namespace: str, payload: dict) -> Optional[Any]:
    key = _cache_key(tenant_id, namespace, payload)
    r = _redis()
    if r:
        try:
            val = r.get(key)
            if val:
                return json.loads(val)
        except Exception as e:
            logger.debug("Redis get failed: %s", e)
    entry = _MEMORY.get(key)
    if entry and entry[0] > time.time():
        return entry[1]
    return None


def set_cached(
    tenant_id: Optional[int],
    namespace: str,
    payload: dict,
    value: Any,
    ttl: Optional[int] = None,
) -> None:
    ttl = ttl or _DEFAULT_TTL
    key = _cache_key(tenant_id, namespace, payload)
    r = _redis()
    if r:
        try:
            r.setex(key, ttl, json.dumps(value, default=str))
            return
        except Exception as e:
            logger.debug("Redis set failed: %s", e)
    _MEMORY[key] = (time.time() + ttl, value)
