"""Hardening pass: POS access cookie gate, Overview hub, client contracts, cash on hand."""
from __future__ import annotations

import os
import re
from decimal import Decimal
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
from app.landing import post_login_path
from app.main import app
from app.models import Product, User
from app.permissions import Perm, can_access_pos, has_permission, user_permissions

ROOT = Path(__file__).resolve().parents[1]


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
        username="hard_admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
    )
    cashier = User(
        username="hard_cashier",
        password_hash=_hash("CashPass1234"),
        role="cashier",
        is_active=True,
    )
    supervisor = User(
        username="hard_super",
        password_hash=_hash("SuperPass1234"),
        role="supervisor",
        is_active=True,
    )
    db.add_all([admin, cashier, supervisor])
    db.commit()
    for u in (admin, cashier, supervisor):
        db.refresh(u)
    return admin, cashier, supervisor


def _login(client, username, password):
    r = client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


# ── Client / Android (WebView) contracts ─────────────────────────────────────


def test_admin_js_create_omits_manual_barcode():
    src = (ROOT / "static/js/admin.js").read_text(encoding="utf-8")
    assert "barcode: null" in src
    assert "Never send a client-chosen barcode" in src
    assert "adminApi('/api/products'" in src or 'adminApi("/api/products"' in src


def test_admin_html_barcode_readonly_and_restock_ui():
    html = (ROOT / "templates/admin.html").read_text(encoding="utf-8")
    assert 'id="prod-barcode"' in html
    assert "readonly" in html
    assert 'id="restock-modal"' in html
    assert 'id="restock-current"' in html
    assert 'id="restock-qty"' in html
    assert 'id="restock-preview"' in html
    assert 'id="btn-toggle-settings"' not in html
    assert 'id="admin-action-settings"' not in html


def test_admin_js_edit_omits_stock_and_restock_uses_quantity_added():
    src = (ROOT / "static/js/admin.js").read_text(encoding="utf-8")
    assert "Do not send stock_qty on edit" in src
    assert "/restock" in src
    assert "quantity_added" in src
    assert "restockInFlight" in src
    restock_block = src[src.find("async function submitRestock") : src.find("async function loadReport")]
    assert "quantity_added" in restock_block
    assert "stock_qty" not in restock_block


def test_android_has_no_native_product_crud_forms():
    """Product create/edit/restock is WebView /admin — no separate Kotlin product forms."""
    kt_files = list((ROOT / "android-app").rglob("*.kt"))
    assert kt_files, "android-app expected"
    product_ui = [
        p
        for p in kt_files
        if re.search(r"Product(Form|Edit|Create|Restock|Admin)", p.name, re.I)
    ]
    assert product_ui == []
    webview = (ROOT / "android-app/app/src/main/java/com/pos/mobile/ui/WebViewActivity.kt").read_text(
        encoding="utf-8"
    )
    assert "/admin" in webview


# ── Access ───────────────────────────────────────────────────────────────────


def test_admin_cookie_redirects_away_from_pos(client, db_session):
    _seed(db_session)
    login = _login(client, "hard_admin", "AdminPass1234")
    assert login.json()["can_access_pos"] is False
    assert auth_mod.POS_ACCESS_COOKIE in login.cookies
    r = client.get("/?pos=1", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert r.headers["location"] == "/overview"


def test_unauthenticated_pos_shows_login_shell(client, db_session):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 200
    assert "login" in r.text.lower()
    assert "pos_user" in r.text


def test_cashier_cookie_keeps_pos(client, db_session):
    _seed(db_session)
    _login(client, "hard_cashier", "CashPass1234")
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 200
    assert "pos-screen" in r.text or "login-screen" in r.text


def test_supervisor_has_sales_and_pos_landing():
    user = User(username="s", role="supervisor", password_hash="x", is_active=True)
    assert has_permission(user, Perm.SALES)
    assert can_access_pos(user)
    assert post_login_path(user) == "/"


def test_platform_owner_role_admin_has_no_automatic_sales():
    """Platform owners are allowlisted separately; tenant admin role still has no sales."""
    ownerish = User(username="owner", role="admin", password_hash="x", is_active=True)
    assert Perm.SALES not in user_permissions(ownerish)
    assert not can_access_pos(ownerish)
    assert post_login_path(ownerish) == "/overview"


def test_multi_role_effective_sales_gate():
    """POS follows effective sales permission, not role label alone."""
    admin = User(username="a", role="admin", password_hash="x", is_active=True)
    cash = User(username="c", role="cashier", password_hash="x", is_active=True)
    assert can_access_pos(admin) is False
    assert can_access_pos(cash) is True


def test_admin_sale_403(client, db_session):
    _seed(db_session)
    tok = _login(client, "hard_admin", "AdminPass1234").json()["access_token"]
    product = Product(
        name="X",
        barcode="AUTO-HARD01",
        stock_qty=5,
        cost_price=Decimal("1"),
        selling_price=Decimal("2"),
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    denied = client.post(
        "/api/sales",
        headers=_auth(tok),
        json={
            "items": [
                {
                    "product_id": product.id,
                    "quantity": 1,
                    "unit_price": 2,
                    "discount": 0,
                }
            ],
            "payments": [{"method": "cash", "amount": 2}],
            "collection_status": "collected",
        },
    )
    assert denied.status_code == 403


def test_index_early_gate_script_blocks_pos_flash(client):
    html = client.get("/").text
    assert "Block POS chrome for signed-in users without sales" in html
    assert "can_access_pos" in html


# ── Overview controls ────────────────────────────────────────────────────────


def test_overview_single_inventory_and_fab_no_admin_settings_dupe(client, db_session):
    _seed(db_session)
    _login(client, "hard_admin", "AdminPass1234")
    ov = client.get("/overview").text
    assert ov.count('href="/admin"') == 1
    assert 'id="ov-fab-notifications"' in ov
    assert 'id="ov-fab-settings"' in ov
    assert 'id="ov-fab-theme"' in ov
    assert ov.count('id="ov-fab-toggle"') == 1
    assert "overview.css?v=11" in ov
    assert ov.count('href="/store-settings"') == 1

    admin_html = client.get("/admin").text
    assert 'id="btn-toggle-settings"' not in admin_html
    assert 'id="admin-action-settings"' not in admin_html
    assert 'id="btn-show-product-form"' in admin_html or "Add product" in admin_html


def test_overview_management_permission_markers(client, db_session):
    _seed(db_session)
    _login(client, "hard_admin", "AdminPass1234")
    html = client.get("/overview").text
    assert 'data-perm="inventory"' in html
    assert 'data-perm="pending"' in html
    assert 'data-perm="refunds"' in html
    assert 'data-perm="layby"' in html
    assert 'href="/billing"' in html
    assert "Subscription and plan billing" in html


def test_logout_clears_access_cookie(client, db_session):
    _seed(db_session)
    _login(client, "hard_admin", "AdminPass1234")
    assert auth_mod.POS_ACCESS_COOKIE in client.cookies
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    set_cookie = (r.headers.get("set-cookie") or "").lower()
    assert "pos_access_token" in set_cookie


def test_saas_login_sets_access_cookie_and_redirects_admin(client, db_session):
    admin, cashier, _ = _seed(db_session)
    admin.email = "hard_admin@example.com"
    cashier.email = "hard_cashier@example.com"
    db_session.commit()

    login = client.post(
        "/auth/login",
        json={"email": "hard_admin@example.com", "password": "AdminPass1234"},
    )
    assert login.status_code == 200, login.text
    assert auth_mod.POS_ACCESS_COOKIE in login.cookies
    body = login.json()
    assert body["access_token"]
    assert body["landing_path"] == "/overview"

    r = client.get("/?pos=1", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert r.headers["location"] == "/overview"

    client.post("/auth/logout", json={})
    # Clear client jar so leftover cookie does not linger if delete is soft
    client.cookies.clear()


def test_saas_login_cashier_keeps_pos(client, db_session):
    admin, cashier, _ = _seed(db_session)
    cashier.email = "hard_cashier@example.com"
    db_session.commit()
    login = client.post(
        "/auth/login",
        json={"email": "hard_cashier@example.com", "password": "CashPass1234"},
    )
    assert login.status_code == 200, login.text
    assert auth_mod.POS_ACCESS_COOKIE in login.cookies
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 200


def test_saas_logout_clears_cookie(client, db_session):
    admin, _, _ = _seed(db_session)
    admin.email = "hard_admin@example.com"
    db_session.commit()
    client.post(
        "/auth/login",
        json={"email": "hard_admin@example.com", "password": "AdminPass1234"},
    )
    r = client.post("/auth/logout", json={})
    assert r.status_code == 200
    assert "pos_access_token" in (r.headers.get("set-cookie") or "").lower()


def test_tampered_cookie_does_not_grant_pos_or_admin(client, db_session):
    _seed(db_session)
    client.cookies.set(auth_mod.POS_ACCESS_COOKIE, "not.a.valid.jwt")
    r = client.get("/?pos=1", follow_redirects=False)
    # Invalid cookie → treat as unauthenticated → serve login shell
    assert r.status_code == 200
    assert "login" in r.text.lower()
    admin_page = client.get("/admin", follow_redirects=False)
    assert admin_page.status_code in (302, 303)
    assert "next=" in admin_page.headers.get("location", "")


def test_expired_cookie_does_not_grant_access(client, db_session):
    from datetime import timedelta

    _seed(db_session)
    token = auth_mod.create_access_token(
        {"sub": "hard_admin", "role": "admin"},
        expires_delta=timedelta(seconds=-10),
    )
    client.cookies.set(auth_mod.POS_ACCESS_COOKIE, token)
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert r.headers["location"].startswith("/?next=")


@pytest.mark.parametrize(
    "path,admin_ok,cashier_ok",
    [
        ("/admin", True, False),
        ("/billing", True, False),
        ("/pending-collection", True, False),
        ("/refunds", True, True),  # cashier has request_refunds
        ("/layby", True, True),  # cashier has sales
        ("/store-settings", True, False),
    ],
)
def test_management_pages_authz(client, db_session, path, admin_ok, cashier_ok):
    _seed(db_session)

    unauth = client.get(path, follow_redirects=False)
    assert unauth.status_code in (302, 303)
    assert unauth.headers["location"].startswith("/?next=")

    _login(client, "hard_admin", "AdminPass1234")
    admin_r = client.get(path, follow_redirects=False)
    if admin_ok:
        assert admin_r.status_code == 200
    else:
        assert admin_r.status_code in (302, 303)
    client.cookies.clear()

    _login(client, "hard_cashier", "CashPass1234")
    cash_r = client.get(path, follow_redirects=False)
    if cashier_ok:
        assert cash_r.status_code == 200
    else:
        # Redirect to cashier landing (/)
        assert cash_r.status_code in (302, 303)
        assert cash_r.headers["location"] in ("/", "/overview") or cash_r.headers[
            "location"
        ].startswith("/?next=")
