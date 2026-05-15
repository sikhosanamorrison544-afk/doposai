"""Simple in-process rate limiting (IP + key). Resets on process restart; use Redis/Cloudflare for scale."""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List

from fastapi import HTTPException, Request

_hits: Dict[str, List[float]] = defaultdict(list)


def rate_limit_hit(request: Request, key: str, max_calls: int = 30, window_sec: int = 60) -> None:
    ip = request.client.host if request.client else "unknown"
    bucket = f"{key}:{ip}"
    now = time.time()
    start = now - window_sec
    _hits[bucket] = [t for t in _hits[bucket] if t > start]
    if len(_hits[bucket]) >= max_calls:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    _hits[bucket].append(now)
