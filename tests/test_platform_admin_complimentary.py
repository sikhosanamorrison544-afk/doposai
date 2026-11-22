"""Platform Owner admin: cross-tenant visibility, complimentary access, isolation."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

os.environ.setdefault("PLATFORM_OWNER_USERNAMES", "owner_test")
os.environ.setdefault("PLATFORM_OWNER_EMAILS", "email-owner@example.com")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401
from app import auth as auth_mod
from app.billing.models import ComplimentaryAccessGrant, Subscription, SubscriptionPayment
from app.billing import service as billing_service
from app.database import Base, get_db
from app.enterprise_models import Branch
from app.main import app
from app.models import User
from app.quotation_models import Tenant


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
            t_owner = Tenant(
                tenant_uid="ten-owner",
                name="Owner Co",
                owner_name="Owner",
                email="email-owner@example.com",
                is_active=True,
                subscription_status="active",
            )
            t_a = Tenant(
                tenant_uid="ten-a",
                name="Alpha Shop",
                owner_name="Alice",
                email="alice@alpha.example.com",
                is_active=True,
                subscription_status="trial",
                trial_ends_at=datetime.utcnow() + timedelta(days=7),
            )
            t_b = Tenant(
                tenant_uid="ten-b",
                name="Beta Shop",
                owner_name="Bob",
                email="bob@beta.example.com",
                is_active=True,
                subscription_status="expired",
            )
            db.add_all([t_owner, t_a, t_b])
            db.flush()

            owner = User(
                username="owner_test",
                email="email-owner@example.com",
                full_name="Platform Owner",
                password_hash=auth_mod.get_password_hash("OwnerPass1"),
                role="admin",
                is_active=True,
                tenant_id=t_owner.id,
            )
            admin_a = User(
                username="alpha_admin",
                email="admin@alpha.example.com",
                full_name="Alpha Admin",
                password_hash=auth_mod.get_password_hash("AlphaPass1"),
                role="admin",
                is_active=True,
                tenant_id=t_a.id,
            )
            cash_a = User(
                username="alpha_cash",
                email="cash@alpha.example.com",
                full_name="Alpha Cashier",
                password_hash=auth_mod.get_password_hash("CashPass1"),
                role="cashier",
                is_active=True,
                tenant_id=t_a.id,
            )
            admin_b = User(
                username="beta_admin",
                email="admin@beta.example.com",
                full_name="Beta Admin",
                password_hash=auth_mod.get_password_hash("BetaPass1"),
                role="admin",
                is_active=True,
                tenant_id=t_b.id,
            )
            db.add_all([owner, admin_a, cash_a, admin_b])
            db.flush()

            db.add_all(
                [
                    Branch(
                        tenant_id=t_a.id,
                        name="Alpha Main",
                        code="A1",
                        address="1 Alpha St",
                        is_active=True,
                        is_default=True,
                        manager_user_id=admin_a.id,
                    ),
                    Branch(
                        tenant_id=t_b.id,
                        name="Beta Main",
                        code="B1",
                        address="2 Beta Ave",
                        is_active=True,
                        is_default=True,
                        manager_user_id=admin_b.id,
                    ),
                ]
            )
            db.add(
                Subscription(
                    tenant_id=t_a.id,
                    plan="starter",
                    status="trial",
                    trial_start=datetime.utcnow(),
                    trial_end=datetime.utcnow() + timedelta(days=7),
                )
            )
            db.add(
                Subscription(
                    tenant_id=t_b.id,
                    plan="business",
                    status="expired",
                    subscription_end=datetime.utcnow() - timedelta(days=3),
                )
            )
            db.commit()
            c.tenant_a_id = t_a.id
            c.tenant_b_id = t_b.id
            c.admin_a_id = admin_a.id
            c.admin_b_id = admin_b.id
        finally:
            db.close()
        yield c
    app.dependency_overrides.clear()


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _owner_headers(client: TestClient) -> dict:
    return {"Authorization": "Bearer " + _login(client, "email-owner@example.com", "OwnerPass1")}


def _admin_a_headers(client: TestClient) -> dict:
    return {
        "Authorization": "Bearer "
        + _login(client, "admin@alpha.example.com", "AlphaPass1")
    }


def test_owner_sees_all_businesses_users_stores(client: TestClient):
    h = _owner_headers(client)
    tenants = client.get("/api/platform/tenants", headers=h)
    assert tenants.status_code == 200, tenants.text
    names = {t["business_name"] for t in tenants.json()}
    assert "Alpha Shop" in names
    assert "Beta Shop" in names

    users = client.get("/api/platform/users", headers=h)
    assert users.status_code == 200
    usernames = {u["username"] for u in users.json()["items"]}
    assert "alpha_admin" in usernames
    assert "beta_admin" in usernames

    stores = client.get("/api/platform/branches", headers=h)
    assert stores.status_code == 200
    store_names = {s["name"] for s in stores.json()["items"]}
    assert "Alpha Main" in store_names
    assert "Beta Main" in store_names


def test_ordinary_admin_cannot_access_platform(client: TestClient):
    h = _admin_a_headers(client)
    for path in (
        "/api/platform/overview",
        "/api/platform/tenants",
        "/api/platform/users",
        "/api/platform/branches",
        "/api/platform/complimentary-grants",
        "/api/platform/audit-logs",
    ):
        r = client.get(path, headers=h)
        assert r.status_code == 403, path


def test_overview_uses_real_counts(client: TestClient):
    h = _owner_headers(client)
    r = client.get("/api/platform/overview", headers=h)
    assert r.status_code == 200
    totals = r.json()["totals"]
    assert totals["businesses"] >= 3
    assert totals["users"] >= 4
    assert totals["stores"] >= 2


def test_complimentary_grant_activates_without_payment(client: TestClient):
    h = _owner_headers(client)
    tid = client.tenant_b_id

    before_payments = client.get(f"/api/platform/payments?tenant_id={tid}", headers=h)
    assert before_payments.status_code == 200
    pay_count_before = before_payments.json()["total"]

    r = client.post(
        "/api/platform/complimentary-grants",
        headers=h,
        json={
            "tenant_id": tid,
            "plan": "pro",
            "reason": "demo",
            "note": "Partner demo",
            "permanent": False,
            "duration_days": 14,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["payment_created"] is False
    assert body["grant"]["active"] is True
    assert body["subscription"]["effective_status"] == "complimentary"
    assert body["subscription"]["access_allowed"] is True
    assert body["subscription"]["effective_plan"] == "pro"
    assert body["subscription"]["entitlement_source"] == "complimentary"

    after_payments = client.get(f"/api/platform/payments?tenant_id={tid}", headers=h)
    assert after_payments.json()["total"] == pay_count_before

    # Direct DB assertion: zero payments created for tenant B in this fixture.
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        n = (
            db.query(func.count(SubscriptionPayment.id))
            .filter(SubscriptionPayment.tenant_id == tid)
            .scalar()
            or 0
        )
        assert n == 0
        grant = (
            db.query(ComplimentaryAccessGrant)
            .filter(ComplimentaryAccessGrant.tenant_id == tid)
            .order_by(ComplimentaryAccessGrant.id.desc())
            .first()
        )
        assert grant is not None
        assert grant.reason == "demo"
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass


def test_expired_and_revoked_grants_stop_access(client: TestClient):
    h = _owner_headers(client)
    tid = client.tenant_b_id

    r = client.post(
        "/api/platform/complimentary-grants",
        headers=h,
        json={
            "tenant_id": tid,
            "plan": "business",
            "reason": "testing",
            "permanent": True,
        },
    )
    assert r.status_code == 200, r.text
    grant_id = r.json()["grant"]["id"]

    # Expire by rewriting ends_at into the past.
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        grant = db.query(ComplimentaryAccessGrant).filter_by(id=grant_id).one()
        grant.ends_at = datetime.utcnow() - timedelta(hours=1)
        # Keep permanent flag off by having ends_at set; revoked_at still None.
        db.commit()
        tenant = db.query(Tenant).filter_by(id=tid).one()
        sub = db.query(Subscription).filter_by(tenant_id=tid).one()
        status, allowed, _ = billing_service.effective_status(sub, tenant, db=db)
        assert status != "complimentary"
        assert allowed is False
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

    # Fresh permanent grant then revoke.
    r = client.post(
        "/api/platform/complimentary-grants",
        headers=h,
        json={
            "tenant_id": tid,
            "plan": "pro",
            "reason": "support",
            "permanent": True,
        },
    )
    assert r.status_code == 200
    grant_id = r.json()["grant"]["id"]
    assert r.json()["subscription"]["access_allowed"] is True

    rev = client.post(
        f"/api/platform/complimentary-grants/{grant_id}/revoke",
        headers=h,
        json={"reason": "Demo over"},
    )
    assert rev.status_code == 200, rev.text
    assert rev.json()["grant"]["active"] is False
    assert rev.json()["subscription"]["effective_status"] != "complimentary"
    assert rev.json()["subscription"]["access_allowed"] is False


def test_permanent_grant_remains_until_revoked(client: TestClient):
    h = _owner_headers(client)
    tid = client.tenant_a_id
    r = client.post(
        "/api/platform/complimentary-grants",
        headers=h,
        json={"tenant_id": tid, "plan": "pro", "reason": "partnership", "permanent": True},
    )
    assert r.status_code == 200
    g = r.json()["grant"]
    assert g["permanent"] is True
    assert g["ends_at"] is None
    assert g["active"] is True
    assert r.json()["subscription"]["access_allowed"] is True


def test_paid_subscription_still_works_alongside_grants(client: TestClient):
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        tid = client.tenant_a_id
        sub = db.query(Subscription).filter_by(tenant_id=tid).one()
        sub.status = "active"
        sub.plan = "business"
        sub.subscription_start = datetime.utcnow() - timedelta(days=5)
        sub.subscription_end = datetime.utcnow() + timedelta(days=25)
        sub.trial_end = None
        tenant = db.query(Tenant).filter_by(id=tid).one()
        tenant.subscription_status = "active"
        db.commit()
        status, allowed, end = billing_service.effective_status(sub, tenant, db=db)
        assert status == "active"
        assert allowed is True
        assert end is not None
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass


def test_tenant_suspend_blocks_even_with_complimentary(client: TestClient):
    h = _owner_headers(client)
    tid = client.tenant_b_id
    client.post(
        "/api/platform/complimentary-grants",
        headers=h,
        json={"tenant_id": tid, "plan": "pro", "reason": "special", "permanent": True},
    )
    sus = client.post(
        f"/api/platform/tenants/{tid}/suspend",
        headers=h,
        json={"reason": "Abuse"},
    )
    assert sus.status_code == 200
    detail = client.get(f"/api/platform/tenants/{tid}", headers=h)
    assert detail.status_code == 200
    assert detail.json()["tenant"]["is_active"] is False
    assert detail.json()["subscription"]["access_allowed"] is False
    assert detail.json()["subscription"]["effective_status"] == "suspended"


def test_audit_log_records_complimentary_actions(client: TestClient):
    h = _owner_headers(client)
    tid = client.tenant_b_id
    r = client.post(
        "/api/platform/complimentary-grants",
        headers=h,
        json={"tenant_id": tid, "plan": "pro", "reason": "promotional", "duration_days": 7},
    )
    assert r.status_code == 200
    logs = client.get("/api/platform/audit-logs", headers=h)
    assert logs.status_code == 200
    actions = {i["action"] for i in logs.json()["items"]}
    assert "platform.complimentary.grant" in actions
