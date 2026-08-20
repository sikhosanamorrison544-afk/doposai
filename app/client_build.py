"""Client-facing build identifier for cache busting after deploys.

Browsers (especially long-lived mobile profiles) may keep stale HTML that
still references old ``?v=`` asset URLs. A single build string stamped into
every HTML shell lets the client detect upgrades and drop Cache Storage /
service workers without touching business data in IndexedDB or localStorage
queues.

Resolution priority:
1. Explicit deploy/release env (``POS_CLIENT_BUILD``, then common CI/Render commit vars)
2. Local ``git rev-parse`` when the working tree is available
3. Development-only fixed fallback — never reused as a stable production id
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Tuple

_ROOT = Path(__file__).resolve().parent.parent
_log = logging.getLogger("pos.client_build")

# Local/dev only. Production must never stamp the same fixed value across releases.
_DEV_FALLBACK = "dev-local-build"


def _app_env() -> str:
    return (os.environ.get("APP_ENV") or "development").strip().lower()


def _is_hex_commit(value: str) -> bool:
    v = value.lower()
    return len(v) >= 7 and all(c in "0123456789abcdef" for c in v)


def _shorten_commit(value: str) -> str:
    if _is_hex_commit(value) and len(value) > 12:
        return value[:12]
    return value[:64]


def _git_short_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(_ROOT),
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        sha = out.decode("utf-8", errors="ignore").strip()
        if sha and all(c.isalnum() for c in sha):
            return sha
    except Exception:
        pass
    return ""


def _env_commit_candidates() -> Tuple[str, str]:
    """Return (raw_value, source_name) for the first explicit deploy identifier."""
    ordered = (
        ("POS_CLIENT_BUILD", "env:POS_CLIENT_BUILD"),
        ("RENDER_GIT_COMMIT", "env:RENDER_GIT_COMMIT"),
        ("SOURCE_VERSION", "env:SOURCE_VERSION"),
        ("SOURCE_COMMIT", "env:SOURCE_COMMIT"),
        ("GITHUB_SHA", "env:GITHUB_SHA"),
        ("COMMIT_SHA", "env:COMMIT_SHA"),
        ("GIT_COMMIT", "env:GIT_COMMIT"),
    )
    for key, source in ordered:
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return raw, source
    return "", ""


def resolve_pos_client_build() -> Tuple[str, str]:
    """Return ``(build_id, source_label)``."""
    raw, source = _env_commit_candidates()
    if raw:
        return _shorten_commit(raw), source

    sha = _git_short_sha()
    if sha:
        return sha, "git:HEAD"

    if _app_env() in ("production", "prod", "staging"):
        # Unique per process start so production never reuses a fixed fallback
        # across releases when commit metadata is missing.
        unique = f"deploy-{int(time.time())}"
        return unique, "fallback:deploy-time"

    return _DEV_FALLBACK, "fallback:dev"


def log_client_build(build: str, source: str) -> None:
    """Safe startup log — build source + abbreviated id only (no secrets)."""
    shown = build if len(build) <= 16 else (build[:12] + "…")
    _log.info("POS client build id source=%s value=%s", source, shown)


POS_CLIENT_BUILD, POS_CLIENT_BUILD_SOURCE = resolve_pos_client_build()
