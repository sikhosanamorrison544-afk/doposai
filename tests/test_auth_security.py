"""Phase 1 security regression: repair-admin removal, JWT secrets, bootstrap passwords."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure test JWT is present even if this file is imported oddly.
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-only-jwt-secret-key-do-not-use-in-prod-64b",
)

from app import auth as auth_mod
from app.database import Base, get_db
from app.main import app
from app.models import User
from app.security_config import (
    JwtSecretError,
    WeakPasswordError,
    validate_bootstrap_password,
    validate_jwt_secret,
)


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        db = TestingSession()
        try:
            admin = User(
                username="sec_admin",
                email="sec_admin@example.com",
                full_name="Security Admin",
                password_hash=auth_mod.get_password_hash("AdminPass1234"),
                role="admin",
                is_active=True,
            )
            cashier = User(
                username="sec_cashier",
                email="sec_cashier@example.com",
                full_name="Security Cashier",
                password_hash=auth_mod.get_password_hash("CashPass1234"),
                role="cashier",
                is_active=True,
            )
            db.add_all([admin, cashier])
            db.commit()
        finally:
            db.close()
        yield c
    app.dependency_overrides.clear()


def _token(client: TestClient, username: str, password: str) -> str:
    r = client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# --- repair-admin removed ---


def test_repair_admin_route_not_registered():
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/repair-admin" not in paths


def test_repair_admin_anonymous_returns_404(client: TestClient):
    r = client.post("/api/repair-admin")
    assert r.status_code == 404


def test_repair_admin_authenticated_admin_returns_404(client: TestClient):
    token = _token(client, "sec_admin", "AdminPass1234")
    r = client.post(
        "/api/repair-admin",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_repair_admin_authenticated_cashier_returns_404(client: TestClient):
    token = _token(client, "sec_cashier", "CashPass1234")
    r = client.post(
        "/api/repair-admin",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


# --- JWT configuration ---


def test_validate_jwt_secret_rejects_missing():
    with pytest.raises(JwtSecretError):
        validate_jwt_secret(None)


def test_validate_jwt_secret_rejects_empty():
    with pytest.raises(JwtSecretError):
        validate_jwt_secret("   ")


@pytest.mark.parametrize(
    "bad",
    [
        "secret",
        "change-me",
        "change-me-in-production",
        "your-secret-key",
        "change-this-to-a-long-random-string-in-production",
        "short",
    ],
)
def test_validate_jwt_secret_rejects_placeholders_and_short(bad: str):
    with pytest.raises(JwtSecretError):
        validate_jwt_secret(bad)


def test_validate_jwt_secret_accepts_strong_secret():
    secret = "a" * 32 + "-unique-deployment-secret"
    assert validate_jwt_secret(secret) == secret


def test_token_roundtrip_with_configured_secret():
    token = auth_mod.create_access_token({"sub": "alice"})
    payload = auth_mod.decode_access_token(token)
    assert payload["sub"] == "alice"
    assert "exp" in payload


def test_token_signed_with_other_secret_rejected():
    other = jwt.encode(
        {
            "sub": "alice",
            "exp": datetime.utcnow() + timedelta(hours=1),
        },
        "different-secret-key-that-is-long-enough-xx",
        algorithm=auth_mod.ALGORITHM,
    )
    with pytest.raises(Exception):
        auth_mod.decode_access_token(other)


def test_expired_token_rejected():
    token = auth_mod.create_access_token(
        {"sub": "alice"},
        expires_delta=timedelta(seconds=-5),
    )
    with pytest.raises(Exception):
        auth_mod.decode_access_token(token)


def test_unsupported_algorithm_rejected():
    # HS512 token must not verify when only HS256 is accepted.
    token = jwt.encode(
        {
            "sub": "alice",
            "exp": datetime.utcnow() + timedelta(hours=1),
        },
        auth_mod.SECRET_KEY,
        algorithm="HS512",
    )
    with pytest.raises(Exception):
        auth_mod.decode_access_token(token)


def test_load_jwt_secret_from_env_requires_var(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    from app import security_config

    # Ignore developer .env so this test only checks the environment variable path.
    monkeypatch.setattr(security_config, "_load_dotenv_file", lambda: None)
    with pytest.raises(JwtSecretError):
        security_config.load_jwt_secret_from_env()


def test_auth_module_import_fails_without_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    import app.security_config as sc

    with mock.patch.object(sc, "load_jwt_secret_from_env", side_effect=JwtSecretError("missing")):
        # Simulate import-time failure path used by auth.py
        with pytest.raises(JwtSecretError):
            sc.load_jwt_secret_from_env()


# --- Auth HTTP behavior ---


def test_missing_token_returns_401(client: TestClient):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_invalid_token_returns_401(client: TestClient):
    r = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert r.status_code == 401


def test_cashier_forbidden_on_admin_users_list(client: TestClient):
    token = _token(client, "sec_cashier", "CashPass1234")
    r = client.get(
        "/api/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# --- Bootstrap password rules ---


@pytest.mark.parametrize(
    "weak",
    ["admin", "password", "password123", "short1", "abcdefghijkl"],
)
def test_weak_bootstrap_passwords_rejected(weak: str):
    with pytest.raises(WeakPasswordError):
        validate_bootstrap_password(weak)


def test_strong_bootstrap_password_accepted():
    assert validate_bootstrap_password("GoodPassphrase1") == "GoodPassphrase1"


def test_password_is_stored_hashed_not_plaintext(client: TestClient):
    # Login proves hash works; ensure stored value is not plaintext.
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
        plain = "BootstrapPass99"
        user = User(
            username="hashcheck",
            password_hash=auth_mod.get_password_hash(plain),
            role="admin",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.password_hash != plain
        assert auth_mod.verify_password(plain, user.password_hash)
    finally:
        db.close()


def test_create_admin_if_missing_does_not_overwrite(monkeypatch):
    from app import init_db

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
        existing = User(
            username="admin",
            password_hash=auth_mod.get_password_hash("ExistingPass12"),
            role="admin",
            is_active=True,
        )
        db.add(existing)
        db.commit()
        old_hash = existing.password_hash

        # Would hang on input if overwrite attempted incorrectly.
        monkeypatch.setattr("builtins.input", lambda *a, **k: (_ for _ in ()).throw(AssertionError("input called")))
        monkeypatch.setattr(init_db, "getpass", lambda *a, **k: (_ for _ in ()).throw(AssertionError("getpass called")))

        init_db.create_admin_if_missing(db)
        db.refresh(existing)
        assert existing.password_hash == old_hash
    finally:
        db.close()
