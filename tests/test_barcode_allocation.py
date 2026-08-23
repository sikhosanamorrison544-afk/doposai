"""
Global AUTO-* barcode allocation regression tests.

Covers:
  - global (not tenant) namespace maximum
  - >50 collisions no longer fail
  - malformed AUTO-* values ignored
  - non-AUTO barcodes unaffected
  - AutoBarcodeAllocator global max + in-file reservation
  - concurrent unique conflict retries
  - controlled 409 on exhausted namespace (no HTTP 500)
  - no partial rows on failure
  - tenant/branch ownership preserved
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
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
from app.enterprise_models import Branch, BranchProductStock
from app.main import app as fastapi_app
from app.models import InventoryMovement, Product, User
from app.quotation_models import Tenant
from app.product_barcodes import (
    AutoBarcodeAllocator,
    BarcodeAllocationError,
    generate_unique_barcode,
)
from app.inventory_service import create_product_with_opening_stock
from app.inventory_service import MOVEMENT_OPENING_STOCK

import app.enterprise_models  # noqa: F401
import app.branch_models  # noqa: F401
import app.accounting_models  # noqa: F401


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    def _override():
        try:
            yield db
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = _override
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


def _tenant(db, name="Barcode Co"):
    t = Tenant(tenant_uid=str(uuid.uuid4()), name=name)
    db.add(t)
    db.flush()
    return t


def _seed_products(db, tenant_id, codes):
    for code in codes:
        db.add(
            Product(
                name=f"P-{code}",
                barcode=code,
                selling_price=1,
                cost_price=1,
                stock_qty=0,
                tenant_id=tenant_id,
            )
        )
    db.flush()


# ---------------------------------------------------------------------------
# Global namespace maximum
# ---------------------------------------------------------------------------
def test_global_max_not_tenant_max(db):
    a = _tenant(db, "Tenant A")
    b = _tenant(db, "Tenant B")
    _seed_products(db, a.id, [f"AUTO-{i:06d}" for i in range(1, 61)])  # global max 60
    # Tenant B has no AUTO codes (smaller local max). Its tenant-scoped
    # sequence would previously start at AUTO-000001.
    db.commit()

    user_b = User(
        username="b_user",
        password_hash="x",
        role="cashier",
        tenant_id=b.id,
        is_active=True,
    )
    db.add(user_b)
    db.commit()

    code = generate_unique_barcode(db, user_b)
    assert code == "AUTO-000061"  # global max + 1, NOT tenant max (which would be 1)


def test_more_than_50_collisions_no_failure(db):
    a = _tenant(db, "Tenant A")
    _seed_products(db, a.id, [f"AUTO-{i:06d}" for i in range(1, 61)])
    db.commit()

    code = generate_unique_barcode(db, None)
    # Any candidate beyond the global max must be returned without the old
    # 50-collision RuntimeError.
    assert code == "AUTO-000061"


def test_malformed_auto_values_ignored(db):
    a = _tenant(db, "Tenant A")
    _seed_products(
        db,
        a.id,
        ["AUTO-000010", "AUTO-ABC", "AUTO-", "AUTO-XYZ12", "AUTO-00012A"],
    )
    db.commit()

    code = generate_unique_barcode(db, None)
    assert code == "AUTO-000011"  # only valid numeric suffix (10) used


def test_non_auto_barcodes_unaffected(db):
    a = _tenant(db, "Tenant A")
    _seed_products(db, a.id, ["AUTO-000005", "CUSTOM-999", "PLAIN-123", "X"])
    db.commit()

    assert generate_unique_barcode(db, None) == "AUTO-000006"


def test_malformed_auto_values_ignored_by_allocator(db):
    a = _tenant(db, "Tenant A")
    _seed_products(db, a.id, ["AUTO-000005", "AUTO-999BOGUS"])
    db.commit()

    alloc = AutoBarcodeAllocator(db)
    # Malformed "AUTO-999BOGUS" must not inflate the global max.
    assert alloc.allocate() == "AUTO-000006"


# ---------------------------------------------------------------------------
# AutoBarcodeAllocator global + in-file reservation
# ---------------------------------------------------------------------------
def test_allocator_uses_global_max(db):
    a = _tenant(db, "Tenant A")
    _tenant(db, "Tenant B")
    _seed_products(db, a.id, [f"AUTO-{i:06d}" for i in range(1, 41)])
    db.commit()

    alloc = AutoBarcodeAllocator(db)
    assert alloc.allocate() == "AUTO-000041"  # global max (40) + 1


def test_allocator_avoids_reserved_in_file(db):
    a = _tenant(db, "Tenant A")
    _seed_products(db, a.id, ["AUTO-000001"])
    db.commit()

    alloc = AutoBarcodeAllocator(db)
    alloc.reserve("AUTO-000002")
    assert alloc.allocate() == "AUTO-000003"
    assert alloc.allocate() == "AUTO-000004"


def test_allocator_avoids_duplicate_auto(db):
    a = _tenant(db, "Tenant A")
    _seed_products(db, a.id, ["AUTO-000001"])
    db.commit()

    alloc = AutoBarcodeAllocator(db)
    first = alloc.allocate()
    second = alloc.allocate()
    assert first == "AUTO-000002"
    assert second == "AUTO-000003"
    assert first != second


# ---------------------------------------------------------------------------
# Concurrent conflict retry + controlled HTTP errors (service-path)
# ---------------------------------------------------------------------------
def _admin_and_branch(db, tenant_id=None):
    t = _tenant(db)
    admin = User(
        username=f"admin_{uuid.uuid4().hex[:8]}",
        password_hash=auth_mod.get_password_hash("AdminPass1234"),
        role="admin",
        tenant_id=t.id,
        is_active=True,
    )
    db.add(admin)
    db.flush()
    branch = Branch(
        tenant_id=t.id, name="Main Branch", code="MAIN", is_default=True, is_active=True
    )
    db.add(branch)
    db.flush()
    return admin, branch


def test_concurrent_conflict_retries_and_succeeds(db, monkeypatch):
    admin, branch = _admin_and_branch(db)
    # Pre-existing product occupies AUTO-000001.
    _seed_products(db, admin.tenant_id, ["AUTO-000001"])
    db.commit()

    calls = {"n": 0}

    def fake_barcode(session, user=None):
        calls["n"] += 1
        # First attempt collides with the existing product; retry must recalc.
        return "AUTO-000001" if calls["n"] == 1 else "AUTO-000002"

    monkeypatch.setattr("app.product_barcodes.generate_unique_barcode", fake_barcode)

    product = create_product_with_opening_stock(
        db,
        user=admin,
        name="Concurrent",
        category_id=None,
        stock_qty=2,
        reserved_qty=0,
        cost_price=1,
        selling_price=2,
        explicit_branch_id=branch.id,
    )
    assert product.barcode == "AUTO-000002"
    # Only the new product plus the pre-existing one.
    assert db.query(Product).count() == 2
    assert (
        db.query(BranchProductStock)
        .filter(BranchProductStock.product_id == product.id)
        .count()
        == 1
    )


def test_exhausted_namespace_returns_409_not_500(db, monkeypatch):
    admin, branch = _admin_and_branch(db)
    db.commit()

    def _exhausted(session, user=None):
        raise BarcodeAllocationError("exhausted")

    monkeypatch.setattr("app.product_barcodes.generate_unique_barcode", _exhausted)

    with pytest.raises(HTTPException) as ei:
        create_product_with_opening_stock(
            db,
            user=admin,
            name="Exhaust",
            category_id=None,
            stock_qty=1,
            reserved_qty=0,
            cost_price=1,
            selling_price=2,
            explicit_branch_id=branch.id,
        )
    assert ei.value.status_code == 409
    # No partial rows.
    assert db.query(Product).count() == 0
    assert db.query(BranchProductStock).count() == 0
    assert db.query(InventoryMovement).count() == 0


# ---------------------------------------------------------------------------
# HTTP-level: controlled 409 and tenant/branch ownership
# ---------------------------------------------------------------------------
def _login(client, username):
    r = client.post(
        "/api/auth/token",
        data={"username": username, "password": "AdminPass1234"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_http_exhausted_namespace_409(client, db, monkeypatch):
    t = _tenant(db)
    admin = User(
        username="owner_exhaust",
        password_hash=auth_mod.get_password_hash("AdminPass1234"),
        role="admin",
        tenant_id=t.id,
        is_active=True,
    )
    db.add(admin)
    db.add(
        Branch(
            tenant_id=t.id, name="Main Branch", code="MAIN", is_default=True, is_active=True
        )
    )
    db.commit()

    monkeypatch.setattr(
        "app.product_barcodes.generate_unique_barcode",
        lambda session, user=None: (_ for _ in ()).throw(BarcodeAllocationError("exhausted")),
    )

    tok = _login(client, "owner_exhaust")
    r = client.post(
        "/api/products",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "name": "Exhausted",
            "barcode": None,
            "category_id": None,
            "stock_qty": 1,
            "cost_price": 1,
            "selling_price": 2,
            "is_active": True,
        },
    )
    assert r.status_code == 409
    assert "barcode" in r.json()["detail"].lower()
    assert db.query(Product).count() == 0


def test_product_remains_on_authenticated_tenant_and_branch(client, db):
    t = _tenant(db)
    admin = User(
        username="owner_scope",
        password_hash=auth_mod.get_password_hash("AdminPass1234"),
        role="admin",
        tenant_id=t.id,
        is_active=True,
    )
    db.add(admin)
    db.flush()
    main = Branch(
        tenant_id=t.id, name="Main Branch", code="MAIN", is_default=True, is_active=True
    )
    db.add(main)
    db.commit()

    tok = _login(client, "owner_scope")
    r = client.post(
        "/api/products",
        headers={"Authorization": f"Bearer {tok}", "X-Branch-Id": str(main.id)},
        json={
            "name": "Scoped",
            "barcode": None,
            "category_id": None,
            "stock_qty": 3,
            "cost_price": 1,
            "selling_price": 2,
            "is_active": True,
        },
    )
    assert r.status_code == 200, r.text
    product = db.query(Product).filter(Product.name == "Scoped").one()
    assert product.tenant_id == t.id
    assert product.barcode.startswith("AUTO-")
    bps = db.query(BranchProductStock).filter(BranchProductStock.product_id == product.id).one()
    assert bps.branch_id == main.id
    assert bps.tenant_id == t.id

    movement = db.query(InventoryMovement).filter(InventoryMovement.product_id == product.id).one()
    assert movement.movement_type == MOVEMENT_OPENING_STOCK
    assert movement.branch_id == main.id