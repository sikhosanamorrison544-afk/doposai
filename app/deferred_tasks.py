"""Fire-and-forget background work (Firestore, etc.) so HTTP handlers return quickly."""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


def run_in_background(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Run callable on a daemon thread; log failures without affecting the request."""

    def _wrapper() -> None:
        try:
            fn(*args, **kwargs)
        except Exception as e:
            logger.warning("Background task %s failed: %s", name, e, exc_info=True)

    threading.Thread(target=_wrapper, name=name[:32], daemon=True).start()
