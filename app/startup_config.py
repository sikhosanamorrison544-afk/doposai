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
IMPORT_ASYNC_MIN_BYTES = int(os.environ.get("IMPORT_ASYNC_MIN_BYTES", "4096"))

# Inventory import limits (large files run in background jobs).
MAX_IMPORT_ROWS = int(os.environ.get("MAX_IMPORT_ROWS", "100000"))
SYNC_IMPORT_MAX_ROWS = int(os.environ.get("SYNC_IMPORT_MAX_ROWS", "0"))
