"""Settings UI contracts: scoped CSS, layout markers, auth, password toggles."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-only-jwt-secret-key-do-not-use-in-prod-64b",
)

from app import auth as auth_mod
from app.database import Base, get_db
from app.main import app
from app.models import User

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_CSS = (ROOT / "static" / "css" / "settings.css").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
STORE_SETTINGS_HTML = (ROOT / "templates" / "store-settings.html").read_text(encoding="utf-8")


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _hash(pw: str) -> str:
    return auth_mod.get_password_hash(pw)


def _seed(db):
    admin = User(
        username="settings_admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
    )
    cashier = User(
        username="settings_cashier",
        password_hash=_hash("CashPass1234"),
        role="cashier",
        is_active=True,
    )
    db.add_all([admin, cashier])
    db.commit()
    return admin, cashier


def _login(client: TestClient, username: str, password: str) -> None:
    r = client.post("/api/auth/token", data={"username": username, "password": password})
    assert r.status_code == 200, r.text


def test_settings_stylesheet_exists_and_is_scoped():
    assert "--settings-max" in SETTINGS_CSS
    assert ".settings-page-container" in SETTINGS_CSS
    assert "min(100% - 2rem, var(--settings-max))" in SETTINGS_CSS
    assert ".settings-grid" in SETTINGS_CSS
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in SETTINGS_CSS
    assert "@media (max-width: 768px)" in SETTINGS_CSS
    assert "grid-template-columns: 1fr" in SETTINGS_CSS
    assert "min-height: var(--settings-touch)" in SETTINGS_CSS
    assert "--settings-touch: 44px" in SETTINGS_CSS
    assert "clamp(1.2rem, 1.8vw, 1.45rem)" in SETTINGS_CSS
    assert "max-height: min(100dvh" in SETTINGS_CSS
    assert "#app *" not in SETTINGS_CSS
    assert "body.page-store-settings" in SETTINGS_CSS
    assert "justify-content: flex-start !important" in SETTINGS_CSS
    assert "max-height: 4.75rem !important" in SETTINGS_CSS

def test_style_css_has_no_new_global_app_star_rule_for_settings():
    # Existing light-theme rules may target #app *; ensure settings.css is not inlined into style.css
    assert "settings.css" not in STYLE_CSS or "@import" not in STYLE_CSS.split("settings")[0][-200:]
    assert "#app * {\n  color:" not in SETTINGS_CSS


def test_cashier_pos_does_not_load_settings_css():
    assert "settings.css" not in INDEX_HTML
    assert 'href="/static/css/settings.css' not in INDEX_HTML


def test_store_settings_template_markers():
    assert 'href="/static/css/settings.css?v=3"' in STORE_SETTINGS_HTML
    assert 'class="store-settings-page-content settings-page-container"' in STORE_SETTINGS_HTML
    assert "settings-page-title" in STORE_SETTINGS_HTML
    assert "settings-form-grid" in STORE_SETTINGS_HTML
    assert "settings-tabs" in STORE_SETTINGS_HTML
    assert 'id="btn-save-settings"' in STORE_SETTINGS_HTML
    assert 'id="cashier-password"' in STORE_SETTINGS_HTML
    assert 'type="password"' in STORE_SETTINGS_HTML
    assert "password-toggle.js" in STORE_SETTINGS_HTML
    assert 'name="viewport"' in STORE_SETTINGS_HTML
    assert "viewport-fit=cover" in STORE_SETTINGS_HTML
    assert 'for="store-name"' in STORE_SETTINGS_HTML
    assert 'for="cashier-username"' in STORE_SETTINGS_HTML
    assert 'data-settings-chrome="compact"' in STORE_SETTINGS_HTML
    assert "settings-top-bar" in STORE_SETTINGS_HTML
    assert 'data-branding="suffix"' in STORE_SETTINGS_HTML
    assert "Back to Overview" in STORE_SETTINGS_HTML
    assert 'href=\'/overview\'' in STORE_SETTINGS_HTML or 'href="/overview"' in STORE_SETTINGS_HTML or "location.href='/overview'" in STORE_SETTINGS_HTML
    assert 'id="backup-api-key"' in STORE_SETTINGS_HTML
    assert 'type="password" id="backup-api-key"' in STORE_SETTINGS_HTML or re.search(
        r'id="backup-api-key"[^>]*type="password"|type="password"[^>]*id="backup-api-key"',
        STORE_SETTINGS_HTML,
    )
    # Field names / actions preserved
    assert 'id="store-name"' in STORE_SETTINGS_HTML
    assert 'id="btn-add-cashier"' in STORE_SETTINGS_HTML
    assert 'id="btn-factory-reset"' in STORE_SETTINGS_HTML
    assert "width:" not in STORE_SETTINGS_HTML or "min(100%" in SETTINGS_CSS
    # No fixed oversized card widths in template
    assert not re.search(r'style="[^"]*width:\s*\d{4,}px', STORE_SETTINGS_HTML)


def test_settings_css_mobile_padding_and_container():
    assert "--settings-pad-desktop: 1.125rem" in SETTINGS_CSS
    assert "--settings-pad-mobile: 0.875rem" in SETTINGS_CSS
    assert "width: min(100% - 1rem, var(--settings-max))" in SETTINGS_CSS
    assert "font-size: 16px" in SETTINGS_CSS  # iOS zoom guard
    assert "--settings-max: 920px" in SETTINGS_CSS


def test_store_settings_requires_auth(client, db_session):
    _seed(db_session)
    r = client.get("/store-settings", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/" in (r.headers.get("location") or "")


def test_cashier_cannot_open_store_settings(client, db_session):
    _seed(db_session)
    _login(client, "settings_cashier", "CashPass1234")
    r = client.get("/store-settings", follow_redirects=False)
    assert r.status_code in (302, 303)


def test_admin_store_settings_page_loads_scoped_assets(client, db_session):
    _seed(db_session)
    _login(client, "settings_admin", "AdminPass1234")
    r = client.get("/store-settings")
    assert r.status_code == 200
    html = r.text
    assert "settings.css?v=3" in html
    assert "settings-page-container" in html
    assert "settings-form-grid" in html
    assert "password-toggle.js" in html
    assert 'id="btn-save-settings"' in html
    assert 'id="cashier-password"' in html
    assert 'name="viewport"' in html
    assert 'data-settings-chrome="compact"' in html
    assert "Back to Overview" in html
    assert "location.href='/overview'" in html


def test_billing_loads_settings_css(client, db_session):
    _seed(db_session)
    _login(client, "settings_admin", "AdminPass1234")
    r = client.get("/billing")
    assert r.status_code == 200
    assert "settings.css?v=3" in r.text
    assert "settings-page-container" in r.text


def test_static_settings_css_served(client):
    r = client.get("/static/css/settings.css?v=3")
    assert r.status_code == 200
    assert ".settings-page-container" in r.text
    assert "page-store-settings" in r.text
    assert "min-height: 3rem" in r.text
    assert "--settings-max: 920px" in r.text
    assert "must-revalidate" in (r.headers.get("cache-control") or "")


def test_settings_css_compact_header_rules():
    assert "settings-top-bar" in STORE_SETTINGS_HTML or "top-bar-brand" in STORE_SETTINGS_HTML
    assert "min-height: 3rem" in SETTINGS_CSS
    assert "height: auto !important" in SETTINGS_CSS
    assert "#app.screen.active" in SETTINGS_CSS
    assert "flex: 0 0 auto !important" in SETTINGS_CSS
    assert "settings-actions-row" in SETTINGS_CSS or ".settings-actions" in SETTINGS_CSS
    assert "white-space: normal !important" in SETTINGS_CSS
