"""Client build stamping and HTML cache headers for post-deploy profile refresh."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-only-jwt-secret-key-do-not-use-in-prod-64b",
)

from app.client_build import (
    POS_CLIENT_BUILD,
    POS_CLIENT_BUILD_SOURCE,
    resolve_pos_client_build,
)
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
BOOT_JS = (ROOT / "static" / "js" / "pos-client-boot.js").read_text(encoding="utf-8")


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_pos_client_build_resolves():
    assert POS_CLIENT_BUILD
    assert POS_CLIENT_BUILD_SOURCE
    assert len(POS_CLIENT_BUILD) >= 4
    build, source = resolve_pos_client_build()
    assert build and source
    # Production must never pin the old fixed marketing fallback across releases.
    assert build != "mobile-cache-fix-v1"


def test_production_missing_commit_uses_unique_deploy_time(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for key in (
        "POS_CLIENT_BUILD",
        "RENDER_GIT_COMMIT",
        "SOURCE_VERSION",
        "SOURCE_COMMIT",
        "GITHUB_SHA",
        "COMMIT_SHA",
        "GIT_COMMIT",
    ):
        monkeypatch.delenv(key, raising=False)

    import app.client_build as cb

    monkeypatch.setattr(cb, "_git_short_sha", lambda: "")
    build, source = cb.resolve_pos_client_build()
    assert source == "fallback:deploy-time"
    assert build.startswith("deploy-")
    assert build != "dev-local-build"
    assert build != "mobile-cache-fix-v1"


def test_index_template_stamps_build():
    assert 'name="pos-build"' in INDEX_HTML
    assert "pos-client-boot.js" in INDEX_HTML
    assert "{{ pos_build }}" in INDEX_HTML


def test_boot_script_preserves_business_keys():
    # Must not wipe auth / offline queue / theme
    assert "pos_token" not in BOOT_JS or "removeItem('pos_token')" not in BOOT_JS
    assert "removeItem('pos_user')" not in BOOT_JS
    assert "removeItem('pos_offline_mutations')" not in BOOT_JS
    assert "IndexedDB" in BOOT_JS or "never touched" in BOOT_JS.lower() or "Preserves" in BOOT_JS
    assert "caches.delete" in BOOT_JS
    assert "serviceWorker" in BOOT_JS
    assert "pos_client_build" in BOOT_JS


def test_html_shell_sends_no_store(client):
    r = client.get("/")
    assert r.status_code == 200
    cc = (r.headers.get("cache-control") or "").lower()
    assert "no-store" in cc or "no-cache" in cc
    assert 'name="pos-build"' in r.text
    assert POS_CLIENT_BUILD in r.text
    assert "pos-client-boot.js" in r.text


def test_client_build_api(client):
    r = client.get("/api/client-build")
    assert r.status_code == 200
    assert r.json()["build"] == POS_CLIENT_BUILD


def test_static_js_has_revalidate(client):
    r = client.get("/static/js/pos-client-boot.js")
    assert r.status_code == 200
    cc = (r.headers.get("cache-control") or "").lower()
    assert "must-revalidate" in cc
    assert "max-age=60" in cc or "max-age=0" in cc or "no-cache" in cc
