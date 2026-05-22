"""Runtime tuning for cloud deployments (memory, timeouts, optional features)."""
from __future__ import annotations

import os

from .config import APP_ENV

# Ollama pre-warm competes with POS/API on small Render instances.
DISABLE_STARTUP_OLLAMA = os.environ.get(
    "DISABLE_STARTUP_OLLAMA",
    "1" if APP_ENV == "production" else "0",
).strip().lower() in ("1", "true", "yes")

# Return 202 before parsing when upload is at least this large (bytes).
IMPORT_ASYNC_MIN_BYTES = int(os.environ.get("IMPORT_ASYNC_MIN_BYTES", "32768"))
