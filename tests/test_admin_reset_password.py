"""Tests for the platform-owner-only password reset endpoint.

We spin up the real FastAPI app against an in-memory SQLite DB so that
the dependency graph (auth, get_db, require_platform_owner) is exercised
end-to-end — that's exactly the surface that the unit-level tests would
miss (route mounting, dependency overrides, token issuing).
"""
from __future__ import annotations

import os

# Set the env vars BEFORE importing app.main so PLATFORM_OWNER_* are
# parsed with our test owner. The module caches them at import time.
os.environ.setdefault("PLATFORM_OWNER_USERNAMES", "owner_test")
os.environ.setdefault("PLATFORM_OWNER_EMAILS", "email-owner@example.com")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401 — registers ORM models + mounts routes
from app import auth as auth_mod
from app.database import Base, get_db
from app.main import app
from app.models import User


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
        # seed: platform owner + a normal customer user
        db = TestingSession()
        try:
            owner = User(
                username="owner_test",
                email="owner@example.com",
                full_name="Platform Owner",
                password_hash=auth_mod.get_password_hash("OwnerPass1"),
                role="admin",
                is_active=True,
            )
            target = User(
                username="cust1",
                email="cust1@example.com",
                full_name="Customer One",
                password_hash=auth_mod.get_password_hash("CustOldPass1"),
                role="cashier",
                is_active=True,
            )
            db.add_all([owner, target])
            db.commit()
        finally:
            db.close()
        yield c
    app.dependency_overrides.clear()


def _owner_token(client: TestClient) -> str:
    r = client.post(
        "/auth/login",
        json={"email": "owner@example.com", "password": "OwnerPass1"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_owner_can_reset_target_user_password(client: TestClient):
    tok = _owner_token(client)

    # Sanity: target can log in with old password
    r = client.post(
        "/auth/login",
        json={"email": "cust1@example.com", "password": "CustOldPass1"},
    )
    assert r.status_code == 200

    # Owner resets target's password
    r = client.post(
        "/api/platform/reset-user-password",
        json={"email": "cust1@example.com", "new_password": "BrandNew2"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["username"] == "cust1"

    # Old password no longer works
    r = client.post(
        "/auth/login",
        json={"email": "cust1@example.com", "password": "CustOldPass1"},
    )
    assert r.status_code == 401

    # New password works
    r = client.post(
        "/auth/login",
        json={"email": "cust1@example.com", "password": "BrandNew2"},
    )
    assert r.status_code == 200


def test_non_owner_admin_cannot_reset(client: TestClient):
    # Create a normal admin (not in PLATFORM_OWNER_USERNAMES)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        db.add(
            User(
                username="local_admin",
                email="localadmin@example.com",
                full_name="Local Admin",
                password_hash=auth_mod.get_password_hash("LocalPass1"),
                role="admin",
                is_active=True,
            )
        )
        db.commit()
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

    r = client.post(
        "/auth/login",
        json={"email": "localadmin@example.com", "password": "LocalPass1"},
    )
    assert r.status_code == 200
    tok = r.json()["access_token"]

    r = client.post(
        "/api/platform/reset-user-password",
        json={"email": "cust1@example.com", "new_password": "NopeNope1"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


def test_unauthenticated_is_rejected(client: TestClient):
    r = client.post(
        "/api/platform/reset-user-password",
        json={"email": "cust1@example.com", "new_password": "BrandNew2"},
    )
    assert r.status_code == 401


def test_weak_password_rejected(client: TestClient):
    tok = _owner_token(client)
    # No digit → fails the validator
    r = client.post(
        "/api/platform/reset-user-password",
        json={"email": "cust1@example.com", "new_password": "lettersonly"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 400


def test_no_selector_returns_400(client: TestClient):
    tok = _owner_token(client)
    r = client.post(
        "/api/platform/reset-user-password",
        json={"new_password": "BrandNew2"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 400


def test_mismatched_selectors_refused(client: TestClient):
    tok = _owner_token(client)
    r = client.post(
        "/api/platform/reset-user-password",
        json={
            "email": "cust1@example.com",
            "username": "owner_test",  # different user
            "new_password": "BrandNew2",
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 400
    assert "different users" in r.json()["detail"]


def test_owner_cannot_target_self(client: TestClient):
    tok = _owner_token(client)
    r = client.post(
        "/api/platform/reset-user-password",
        json={"username": "owner_test", "new_password": "BrandNew2"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 400
