"""API key auth — Render backend must send X-API-Key."""
from __future__ import annotations

from fastapi import Header, HTTPException

from .. import config


def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    if not config.API_KEY:
        raise HTTPException(status_code=503, detail="AI_SERVICE_API_KEY not configured")
    if x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
