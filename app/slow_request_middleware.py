"""Log slow HTTP requests to spot 502 risks before the gateway times out."""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

SLOW_REQUEST_SEC = 10.0
SKIP_PATHS = frozenset({"/health"})


class SlowRequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        path = request.url.path
        if path not in SKIP_PATHS and elapsed >= SLOW_REQUEST_SEC:
            logger.warning(
                "Slow request %.2fs %s %s",
                elapsed,
                request.method,
                path,
            )
        return response
