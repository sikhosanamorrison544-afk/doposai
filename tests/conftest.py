"""
Pytest bootstrap: set a deterministic test-only JWT secret before app imports.

Production and local servers must set JWT_SECRET_KEY in the environment / .env.
This value is for automated tests only and must never be used in real deployments.
"""
from __future__ import annotations

import os

import pytest

# Must run before any test module imports app.auth / app.main.
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-only-jwt-secret-key-do-not-use-in-prod-64b",
)


@pytest.fixture(autouse=True)
def _clear_http_rate_limits():
    """In-process rate-limit buckets accumulate across tests in one process."""
    from app.http_rate_limit import _hits

    _hits.clear()
    yield
    _hits.clear()
