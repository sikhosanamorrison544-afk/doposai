"""Password-reset multi-tenant isolation: store name and user identity from token only."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

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
from app.models import StoreSettings, User
from app.quotation_models import Tenant
from app.saas_models import PasswordResetToken, RefreshToken


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


def _seed_two_stores(db):
    """Store A and Store B with distinct users; optional duplicate-email case."""
    tenant_a = Tenant(
        tenant_uid="tenant-a-uid",
        name="Tenant A Co",
        email="owner-a@example.com",
        is_active=True,
        subscription_status="active",
    )
    tenant_b = Tenant(
        tenant_uid="tenant-b-uid",
        name="Tenant B Co",
        email="owner-b@example.com",
        is_active=True,
        subscription_status="active",
    )
    db.add_all([tenant_a, tenant_b])
    db.flush()

    user_a = User(
        username="user_store_a",
        email="alice@store-a.example",
        full_name="Alice A",
        password_hash=_hash("OldPassA123"),
        role="admin",
        tenant_id=tenant_a.id,
        is_active=True,
    )
    user_b = User(
        username="user_store_b",
        email="bob@store-b.example",
        full_name="Bob B",
        password_hash=_hash("OldPassB123"),
        role="admin",
        tenant_id=tenant_b.id,
        is_active=True,
    )
    # Same email string across tenants (DB allows; registration normally blocks).
    twin_a = User(
        username="twin_a",
        email="shared@example.com",
        full_name="Twin A",
        password_hash=_hash("TwinPassA1"),
        role="admin",
        tenant_id=tenant_a.id,
        is_active=True,
    )
    twin_b = User(
        username="twin_b",
        email="shared@example.com",
        full_name="Twin B",
        password_hash=_hash("TwinPassB1"),
        role="admin",
        tenant_id=tenant_b.id,
        is_active=True,
    )
    db.add_all([user_a, user_b, twin_a, twin_b])
    db.flush()

    db.add(
        StoreSettings(
            tenant_id=tenant_a.id,
            store_name="Store Alpha",
            currency="USD",
        )
    )
    db.add(
        StoreSettings(
            tenant_id=tenant_b.id,
            store_name="Store Beta",
            currency="USD",
        )
    )
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)
    db.refresh(twin_a)
    db.refresh(twin_b)
    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
        "twin_a": twin_a,
        "twin_b": twin_b,
    }


def _issue_token(db, user: User, *, hours: float = 24, used: bool = False) -> str:
    raw = secrets.token_urlsafe(32)
    row = PasswordResetToken(
        user_id=user.id,
        token_hash=auth_mod.hash_token(raw),
        expires_at=datetime.utcnow() + timedelta(hours=hours),
        used_at=datetime.utcnow() if used else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return raw


def test_validate_returns_token_user_store_not_other_store(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])

    r = client.get(f"/auth/reset-password/validate?token={raw}")
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["storeName"] == "Store Alpha"
    assert data["maskedEmail"] == "a***@store-a.example"
    assert "Store Beta" not in (data["storeName"] or "")


def test_store_b_localstorage_context_cannot_change_validate_identity(client, db_session):
    """Simulate browser logged into Store B / cached Store B while resetting Store A."""
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])

    # Client sends Authorization for Store B + bogus store/tenant hints in query —
    # validate endpoint ignores them and uses only the token.
    login_b = client.post(
        "/auth/login",
        json={"email": "bob@store-b.example", "password": "OldPassB123"},
    )
    assert login_b.status_code == 200
    access_b = login_b.json()["access_token"]

    r = client.get(
        f"/auth/reset-password/validate?token={raw}"
        f"&store_id={seeded['tenant_b'].id}&tenant_id={seeded['tenant_b'].id}",
        headers={"Authorization": f"Bearer {access_b}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["storeName"] == "Store Alpha"
    assert data["maskedEmail"] == "a***@store-a.example"


def test_duplicate_email_tokens_are_user_scoped(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw_a = _issue_token(db_session, seeded["twin_a"])
    raw_b = _issue_token(db_session, seeded["twin_b"])

    va = client.get(f"/auth/reset-password/validate?token={raw_a}").json()
    vb = client.get(f"/auth/reset-password/validate?token={raw_b}").json()
    assert va["valid"] and vb["valid"]
    assert va["storeName"] == "Store Alpha"
    assert vb["storeName"] == "Store Beta"
    assert va["maskedEmail"] == vb["maskedEmail"] == "s***@example.com"


def test_store_a_token_never_returns_store_b_info(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])
    data = client.get(f"/auth/reset-password/validate?token={raw}").json()
    assert data["storeName"] == "Store Alpha"
    assert data["storeName"] != "Store Beta"
    assert "beta" not in data["storeName"].lower()
    assert "store-b" not in (data["maskedEmail"] or "").lower()


def test_client_store_b_id_with_store_a_token_ignored_on_reset(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])
    old_b_hash = seeded["user_b"].password_hash

    r = client.post(
        "/auth/reset-password",
        json={
            "token": raw,
            "new_password": "NewPassA999",
            "confirm_password": "NewPassA999",
            "store_id": seeded["tenant_b"].id,
            "tenant_id": seeded["tenant_b"].id,
            "user_id": seeded["user_b"].id,
            "email": seeded["user_b"].email,
        },
    )
    assert r.status_code == 200
    db_session.refresh(seeded["user_a"])
    db_session.refresh(seeded["user_b"])
    assert auth_mod.verify_password("NewPassA999", seeded["user_a"].password_hash)
    assert seeded["user_b"].password_hash == old_b_hash
    assert not auth_mod.verify_password("NewPassA999", seeded["user_b"].password_hash)


def test_client_other_user_id_with_valid_token_ignored(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])
    old_b = seeded["user_b"].password_hash

    r = client.post(
        "/auth/reset-password",
        json={
            "token": raw,
            "new_password": "OnlyAlice88",
            "user_id": seeded["user_b"].id,
        },
    )
    assert r.status_code == 200
    db_session.refresh(seeded["user_a"])
    db_session.refresh(seeded["user_b"])
    assert auth_mod.verify_password("OnlyAlice88", seeded["user_a"].password_hash)
    assert seeded["user_b"].password_hash == old_b


def test_expired_token_rejected(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"], hours=-1)
    assert client.get(f"/auth/reset-password/validate?token={raw}").json()["valid"] is False
    r = client.post(
        "/auth/reset-password",
        json={"token": raw, "new_password": "NewPassA999"},
    )
    assert r.status_code == 400


def test_used_token_rejected(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"], used=True)
    assert client.get(f"/auth/reset-password/validate?token={raw}").json()["valid"] is False
    r = client.post(
        "/auth/reset-password",
        json={"token": raw, "new_password": "NewPassA999"},
    )
    assert r.status_code == 400


def test_invalid_token_rejected(client, db_session):
    _seed_two_stores(db_session)
    junk = secrets.token_urlsafe(32)
    assert client.get(f"/auth/reset-password/validate?token={junk}").json()["valid"] is False
    r = client.post(
        "/auth/reset-password",
        json={"token": junk, "new_password": "NewPassA999"},
    )
    assert r.status_code == 400


def test_password_changes_only_token_user_others_unchanged(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])
    hashes = {
        "a": seeded["user_a"].password_hash,
        "b": seeded["user_b"].password_hash,
        "ta": seeded["twin_a"].password_hash,
        "tb": seeded["twin_b"].password_hash,
    }
    assert (
        client.post(
            "/auth/reset-password",
            json={
                "token": raw,
                "new_password": "FreshPassA1",
                "confirm_password": "FreshPassA1",
            },
        ).status_code
        == 200
    )
    for u in (seeded["user_a"], seeded["user_b"], seeded["twin_a"], seeded["twin_b"]):
        db_session.refresh(u)
    assert auth_mod.verify_password("FreshPassA1", seeded["user_a"].password_hash)
    assert not auth_mod.verify_password("OldPassA123", seeded["user_a"].password_hash)
    assert seeded["user_b"].password_hash == hashes["b"]
    assert seeded["twin_a"].password_hash == hashes["ta"]
    assert seeded["twin_b"].password_hash == hashes["tb"]


def test_token_cannot_be_reused_after_success(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])
    assert (
        client.post(
            "/auth/reset-password",
            json={"token": raw, "new_password": "OnceOnly99"},
        ).status_code
        == 200
    )
    assert client.get(f"/auth/reset-password/validate?token={raw}").json()["valid"] is False
    r = client.post(
        "/auth/reset-password",
        json={"token": raw, "new_password": "SecondTry99"},
    )
    assert r.status_code == 400
    db_session.refresh(seeded["user_a"])
    assert auth_mod.verify_password("OnceOnly99", seeded["user_a"].password_hash)
    assert not auth_mod.verify_password("SecondTry99", seeded["user_a"].password_hash)


def test_sibling_unused_tokens_invalidated_on_reset(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw1 = _issue_token(db_session, seeded["user_a"])
    raw2 = _issue_token(db_session, seeded["user_a"])
    # Issuing via helper doesn't invalidate siblings; simulate two outstanding.
    assert client.get(f"/auth/reset-password/validate?token={raw1}").json()["valid"] is True
    assert client.get(f"/auth/reset-password/validate?token={raw2}").json()["valid"] is True

    assert (
        client.post(
            "/auth/reset-password",
            json={"token": raw2, "new_password": "SiblingKill1"},
        ).status_code
        == 200
    )
    assert client.get(f"/auth/reset-password/validate?token={raw1}").json()["valid"] is False
    assert client.get(f"/auth/reset-password/validate?token={raw2}").json()["valid"] is False


def test_forgot_password_does_not_reveal_email_existence(client, db_session):
    _seed_two_stores(db_session)
    known = client.post(
        "/auth/forgot-password",
        json={"email": "alice@store-a.example"},
    )
    unknown = client.post(
        "/auth/forgot-password",
        json={"email": "nobody@missing.example"},
    )
    assert known.status_code == 200
    assert unknown.status_code == 200
    assert known.json() == unknown.json()
    assert "exists" not in known.json()["message"].lower() or "if that email exists" in known.json()["message"].lower()


def test_forgot_password_issues_token_for_each_duplicate_email(client, db_session):
    seeded = _seed_two_stores(db_session)
    r = client.post("/auth/forgot-password", json={"email": "shared@example.com"})
    assert r.status_code == 200
    rows = (
        db_session.query(PasswordResetToken)
        .filter(PasswordResetToken.used_at.is_(None))
        .all()
    )
    user_ids = {row.user_id for row in rows}
    assert seeded["twin_a"].id in user_ids
    assert seeded["twin_b"].id in user_ids


def test_reset_tokens_stored_as_hash_not_plaintext(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])
    row = db_session.query(PasswordResetToken).one()
    assert row.token_hash == auth_mod.hash_token(raw)
    assert row.token_hash != raw
    assert len(row.token_hash) == 64


def test_login_works_with_new_password_old_fails(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])
    assert (
        client.post(
            "/auth/reset-password",
            json={"token": raw, "new_password": "BrandNewA1"},
        ).status_code
        == 200
    )
    bad = client.post(
        "/auth/login",
        json={"email": "alice@store-a.example", "password": "OldPassA123"},
    )
    good = client.post(
        "/auth/login",
        json={"email": "alice@store-a.example", "password": "BrandNewA1"},
    )
    assert bad.status_code == 401
    assert good.status_code == 200
    assert good.json()["user_id"] == seeded["user_a"].id


def test_existing_refresh_sessions_revoked_on_reset(client, db_session):
    seeded = _seed_two_stores(db_session)
    login = client.post(
        "/auth/login",
        json={"email": "alice@store-a.example", "password": "OldPassA123"},
    )
    assert login.status_code == 200
    refresh = login.json()["refresh_token"]
    assert (
        client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 200
    )

    raw = _issue_token(db_session, seeded["user_a"])
    assert (
        client.post(
            "/auth/reset-password",
            json={"token": raw, "new_password": "AfterRevoke1"},
        ).status_code
        == 200
    )
    revoked = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert revoked.status_code in (401, 400)

    active = (
        db_session.query(RefreshToken)
        .filter(
            RefreshToken.user_id == seeded["user_a"].id,
            RefreshToken.revoked_at.is_(None),
        )
        .count()
    )
    assert active == 0


def test_reset_page_html_omits_store_branding_script(client, db_session):
    _seed_two_stores(db_session)
    r = client.get("/reset-password?token=placeholder-token-xx")
    assert r.status_code == 200
    html = r.text
    assert "store-branding.js" not in html
    assert "page-reset-password" in html
    assert "/auth/reset-password/validate" in html
    # Must not bake a tenant store name into the shell for branding overwrite.
    assert "Store Alpha" not in html
    assert "Store Beta" not in html


def test_authenticated_browser_state_does_not_affect_reset_identity(client, db_session):
    seeded = _seed_two_stores(db_session)
    login_b = client.post(
        "/auth/login",
        json={"email": "bob@store-b.example", "password": "OldPassB123"},
    )
    assert login_b.status_code == 200
    headers = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

    raw = _issue_token(db_session, seeded["user_a"])
    data = client.get(
        f"/auth/reset-password/validate?token={raw}",
        headers=headers,
    ).json()
    assert data["storeName"] == "Store Alpha"
    assert data["maskedEmail"] == "a***@store-a.example"

    # Store-settings for logged-in B must still be B — and must not leak into validate.
    settings_b = client.get("/api/store-settings", headers=headers)
    if settings_b.status_code == 200:
        assert settings_b.json().get("store_name") == "Store Beta"
    assert data["storeName"] != "Store Beta"


def test_missing_store_a_settings_never_falls_back_to_store_b(client, db_session, monkeypatch):
    seeded = _seed_two_stores(db_session)
    # Remove Store A settings only; Store B settings remain.
    db_session.query(StoreSettings).filter(
        StoreSettings.tenant_id == seeded["tenant_a"].id
    ).delete()
    db_session.commit()

    # Even if env STORE_NAME is Store B's name, validate must not use it.
    monkeypatch.setenv("STORE_NAME", "Store Beta")
    import app.saas_auth_routes as sar

    monkeypatch.setattr(sar, "PLATFORM_BRAND_NAME", "Neutral Platform Brand", raising=False)

    raw = _issue_token(db_session, seeded["user_a"])
    data = client.get(f"/auth/reset-password/validate?token={raw}").json()
    assert data["valid"] is True
    # Falls back to Tenant.name for Store A — never Store Beta settings / env.
    assert data["storeName"] == "Tenant A Co"
    assert data["storeName"] != "Store Beta"


def test_store_settings_query_scoped_to_token_user_tenant(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])
    from app.saas_auth_routes import _lookup_reset_token, _store_name_for_user

    row, user = _lookup_reset_token(db_session, raw)
    assert user is not None and user.id == seeded["user_a"].id
    assert user.tenant_id == seeded["tenant_a"].id
    name = _store_name_for_user(db_session, user)
    assert name == "Store Alpha"
    # Confirm Store B row exists but is not selected for user A.
    assert (
        db_session.query(StoreSettings)
        .filter(StoreSettings.tenant_id == seeded["tenant_b"].id)
        .one()
        .store_name
        == "Store Beta"
    )


def test_validate_and_reset_page_send_cache_control_no_store(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])

    page = client.get(f"/reset-password?token={raw}")
    assert page.status_code == 200
    page_cc = (page.headers.get("cache-control") or "").lower()
    assert "no-store" in page_cc
    assert (page.headers.get("pragma") or "").lower() == "no-cache"

    val = client.get(f"/auth/reset-password/validate?token={raw}")
    assert val.status_code == 200
    val_cc = (val.headers.get("cache-control") or "").lower()
    assert "no-store" in val_cc
    assert "private" in val_cc
    assert (val.headers.get("pragma") or "").lower() == "no-cache"


def test_reset_page_does_not_use_shared_branding_or_storage(client, db_session):
    r = client.get("/reset-password?token=placeholder-token-xx")
    html = r.text
    assert "store-branding.js" not in html
    assert "PosBranding" not in html
    assert "/api/store-settings" not in html
    assert "pos_store_branding" not in html
    assert "localStorage" not in html
    assert "sessionStorage" not in html
    assert "pos_token" not in html
    assert 'id="reset-account-store"' in html
    assert "shop-name" not in html
    assert "Validating password-reset link" in html
    assert "textContent" in html
    # Store name must be assigned via textContent, never innerHTML.
    assert "storeEl.innerHTML" not in html
    assert "storeEl.textContent" in html or "reset-account-store" in html


def test_invalid_expired_used_tokens_expose_no_store_name(client, db_session):
    seeded = _seed_two_stores(db_session)
    junk = secrets.token_urlsafe(32)
    expired = _issue_token(db_session, seeded["user_a"], hours=-2)
    used = _issue_token(db_session, seeded["user_a"], used=True)

    for raw in (junk, expired, used):
        data = client.get(f"/auth/reset-password/validate?token={raw}").json()
        assert data["valid"] is False
        assert data["storeName"] is None
        assert data["maskedEmail"] is None


def test_service_worker_excludes_password_reset_routes(client):
    from pathlib import Path

    sw = (Path(__file__).resolve().parents[1] / "static" / "sw.js").read_text(
        encoding="utf-8"
    )
    boot = (
        Path(__file__).resolve().parents[1] / "static" / "js" / "pos-client-boot.js"
    ).read_text(encoding="utf-8")

    assert "pos-sw-v4-transfers-network-only" in sw
    assert "/reset-password" in sw
    assert "/auth/reset-password" in sw
    assert "/auth/reset-password/validate" in sw
    assert "cache: 'no-store'" in sw or 'cache: "no-store"' in sw
    assert "PASSWORD_RESET_PATH_MARKERS" in boot
    assert "unregisterAllServiceWorkers" in boot or "unregister" in boot
    assert "/sw.js" in boot

    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "no-store" in (r.headers.get("cache-control") or "").lower()
    assert "/reset-password" in r.text
    assert "pos-sw-v4-transfers-network-only" in r.text


def test_store_branding_js_skips_reset_page_and_reset_ids():
    from pathlib import Path

    branding = (
        Path(__file__).resolve().parents[1] / "static" / "js" / "store-branding.js"
    ).read_text(encoding="utf-8")
    assert "page-reset-password" in branding
    assert "reset-account-store" in branding
    assert "pos_store_branding" in branding


def test_reset_page_locks_store_name_to_validation_response(client, db_session):
    """Inline script must assign #reset-account-store from validation.storeName only."""
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])
    api = client.get(f"/auth/reset-password/validate?token={raw}").json()
    assert api["storeName"] == "Store Alpha"

    html = client.get(f"/reset-password?token={raw}").text
    assert "data.storeName" in html
    assert "storeEl.textContent" in html
    assert "lastValidationStoreName" in html
    assert "applyValidationIdentity" in html or "showValid(data.storeName" in html
    # Must not seed Store B (or any tenant) into the shell before validation.
    assert "Store Beta" not in html
    assert "Store Alpha" not in html


def test_auth_reset_paths_always_send_no_store_headers(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])
    for path in (
        f"/reset-password?token={raw}",
        f"/auth/reset-password/validate?token={raw}",
    ):
        r = client.get(path)
        assert r.status_code == 200
        cc = (r.headers.get("cache-control") or "").lower()
        assert "no-store" in cc
        assert "private" in cc
        assert (r.headers.get("pragma") or "").lower() == "no-cache"


def test_boot_js_unregisters_sw_on_reset_page():
    from pathlib import Path

    boot = (
        Path(__file__).resolve().parents[1] / "static" / "js" / "pos-client-boot.js"
    ).read_text(encoding="utf-8")
    assert "unregisterAllServiceWorkers" in boot
    assert "isPasswordResetPage()" in boot
    assert "pos-sw-v4-transfers-network-only" not in boot  # version lives in sw.js
    assert "purgePasswordResetFromCaches" in boot


def test_password_update_still_only_token_user(client, db_session):
    seeded = _seed_two_stores(db_session)
    raw = _issue_token(db_session, seeded["user_a"])
    old_b = seeded["user_b"].password_hash
    assert (
        client.post(
            "/auth/reset-password",
            json={
                "token": raw,
                "new_password": "StillOnlyA1",
                "confirm_password": "StillOnlyA1",
            },
        ).status_code
        == 200
    )
    db_session.refresh(seeded["user_a"])
    db_session.refresh(seeded["user_b"])
    assert auth_mod.verify_password("StillOnlyA1", seeded["user_a"].password_hash)
    assert seeded["user_b"].password_hash == old_b
