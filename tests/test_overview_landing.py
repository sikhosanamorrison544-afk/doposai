"""Business Overview landing + dashboard API (role routing, isolation, empty data)."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from decimal import Decimal

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
from app.enterprise_models import Branch
from app.landing import LANDING_OVERVIEW, LANDING_POS, post_login_path
from app.main import app
from app.models import (
    Customer,
    Payment,
    Product,
    Refund,
    Sale,
    SaleItem,
    StoreSettings,
    User,
    Withdrawal,
)
from app.quotation_models import Tenant


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


def _seed_users(db, *, tenant_a=None, tenant_b=None):
    admin = User(
        username="ov_admin",
        email="ov_admin@example.com",
        full_name="Overview Admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
        tenant_id=tenant_a,
    )
    cashier = User(
        username="ov_cashier",
        email="ov_cashier@example.com",
        full_name="Overview Cashier",
        password_hash=_hash("CashPass1234"),
        role="cashier",
        is_active=True,
        tenant_id=tenant_a,
    )
    supervisor = User(
        username="ov_supervisor",
        email="ov_sup@example.com",
        full_name="Overview Supervisor",
        password_hash=_hash("SuperPass1234"),
        role="supervisor",
        is_active=True,
        tenant_id=tenant_a,
    )
    db.add_all([admin, cashier, supervisor])
    if tenant_b is not None:
        other_admin = User(
            username="ov_other_admin",
            email="ov_other@example.com",
            full_name="Other Admin",
            password_hash=_hash("AdminPass1234"),
            role="admin",
            is_active=True,
            tenant_id=tenant_b,
        )
        db.add(other_admin)
    db.commit()
    for u in db.query(User).all():
        db.refresh(u)
    return admin, cashier, supervisor


def _login(client: TestClient, username: str, password: str) -> dict:
    r = client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- Landing resolver ---


def test_post_login_path_roles():
    assert post_login_path(role="admin") == LANDING_OVERVIEW
    assert post_login_path(role="owner") == LANDING_OVERVIEW
    assert post_login_path(role="cashier") == LANDING_POS
    assert post_login_path(role="supervisor") == LANDING_POS


def test_can_access_overview_permission():
    from app.landing import can_access_overview
    from app.models import User

    admin = User(username="a", role="admin", password_hash="x", is_active=True)
    supervisor = User(username="s", role="supervisor", password_hash="x", is_active=True)
    cashier = User(username="c", role="cashier", password_hash="x", is_active=True)
    assert can_access_overview(admin) is True
    assert can_access_overview(supervisor) is True
    assert can_access_overview(cashier) is False


def test_login_returns_landing_path(client, db_session):
    _seed_users(db_session)
    admin_tok = _login(client, "ov_admin", "AdminPass1234")
    assert admin_tok["landing_path"] == "/overview"
    cash_tok = _login(client, "ov_cashier", "CashPass1234")
    assert cash_tok["landing_path"] == "/"
    sup_tok = _login(client, "ov_supervisor", "SuperPass1234")
    assert sup_tok["landing_path"] == "/"


def test_me_includes_landing_path(client, db_session):
    _seed_users(db_session)
    tok = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    me = client.get("/api/auth/me", headers=_auth(tok))
    assert me.status_code == 200
    assert me.json()["landing_path"] == "/overview"


def test_overview_page_served(client, db_session):
    _seed_users(db_session)
    _login(client, "ov_admin", "AdminPass1234")
    r = client.get("/overview")
    assert r.status_code == 200
    assert b"Business Overview" in r.content
    assert b"overview.js" in r.content


def test_overview_page_requires_auth(client, db_session):
    r = client.get("/overview", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "next=" in r.headers.get("location", "")


def test_analytics_redirects_to_overview(client, db_session):
    r = client.get("/analytics", follow_redirects=False)
    assert r.status_code in (301, 302, 307, 308)
    assert "/overview" in r.headers.get("location", "")


def test_pos_index_still_served(client, db_session):
    r = client.get("/")
    assert r.status_code == 200
    assert b"pos-screen" in r.content or b"login" in r.content.lower()


# --- Overview API ---


def test_overview_requires_auth(client, db_session):
    r = client.get("/api/overview/summary")
    assert r.status_code in (401, 403)


def test_cashier_forbidden_on_overview_api(client, db_session):
    _seed_users(db_session)
    tok = _login(client, "ov_cashier", "CashPass1234")["access_token"]
    r = client.get("/api/overview/summary", headers=_auth(tok))
    assert r.status_code == 403


def test_overview_empty_business_zeros(client, db_session):
    _seed_users(db_session)
    db_session.add(StoreSettings(store_name="Empty Shop"))
    db_session.commit()
    tok = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    r = client.get("/api/overview/summary", headers=_auth(tok))
    assert r.status_code == 200
    data = r.json()
    assert data["business"]["name"] == "Empty Shop"
    assert data["summary"]["revenue"] == 0
    assert data["summary"]["completed_sales"] == 0
    assert data["summary"]["cash_on_hand"] == 0
    assert data["sales_trend"] == []
    assert data["payment_methods"] == []
    assert data["top_products"] == []
    assert isinstance(data["cards"], list)
    assert any(c["key"] == "cash_on_hand" for c in data["cards"])
    assert data["meta"]["stock_source"] == "products.stock_qty"
    assert data["cash_on_hand_meta"]["meaning"] == "period"
    assert data["cash_on_hand_meta"]["scope"] == "tenant"
    assert data["cash_on_hand_meta"]["available"] is True
    assert "Cash activity for selected period" in data["cash_on_hand_meta"]["subtitle"]


def test_overview_rejects_invalid_date_range(client, db_session):
    _seed_users(db_session)
    tok = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    r = client.get(
        "/api/overview/summary",
        params={"from_date": "2026-08-10", "to_date": "2026-08-01"},
        headers=_auth(tok),
    )
    assert r.status_code == 400


def test_overview_sales_and_payments(client, db_session):
    admin, cashier, _ = _seed_users(db_session)
    product = Product(
        name="Widget",
        barcode="W1",
        stock_qty=50,
        cost_price=Decimal("4.00"),
        selling_price=Decimal("10.00"),
        is_active=True,
        low_stock_threshold=5,
    )
    db_session.add(product)
    db_session.flush()
    today = datetime.now()
    sale = Sale(
        created_at=today,
        cashier_id=cashier.id,
        subtotal=Decimal("20.00"),
        discount_total=Decimal("0"),
        total=Decimal("20.00"),
        collection_status="collected",
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=2,
            unit_price=Decimal("10.00"),
            discount=Decimal("0"),
            line_total=Decimal("20.00"),
        )
    )
    db_session.add(
        Payment(sale_id=sale.id, method="cash", amount=Decimal("20.00"))
    )
    db_session.commit()

    tok = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    r = client.get(
        "/api/overview/summary",
        params={
            "from_date": date.today().isoformat(),
            "to_date": date.today().isoformat(),
        },
        headers=_auth(tok),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["completed_sales"] == 1
    assert data["summary"]["revenue"] == 20.0
    assert data["summary"]["gross_profit"] == 12.0  # 20 - 2*4
    assert data["summary"]["average_transaction_value"] == 20.0
    methods = {m["method"]: m["amount"] for m in data["payment_methods"]}
    assert methods.get("cash") == 20.0
    assert data["top_products"][0]["name"] == "Widget"
    assert data["top_products"][0]["quantity"] == 2


def test_overview_approved_refunds_reduce_revenue(client, db_session):
    admin, cashier, _ = _seed_users(db_session)
    product = Product(
        name="Gadget",
        stock_qty=10,
        cost_price=Decimal("1.00"),
        selling_price=Decimal("5.00"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    sale = Sale(
        created_at=datetime.now(),
        cashier_id=cashier.id,
        subtotal=Decimal("5.00"),
        discount_total=Decimal("0"),
        total=Decimal("5.00"),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=1,
            unit_price=Decimal("5.00"),
            discount=Decimal("0"),
            line_total=Decimal("5.00"),
        )
    )
    db_session.add(
        Refund(
            sale_id=sale.id,
            refund_number="RF-TEST-1",
            amount=Decimal("5.00"),
            status="approved",
            reason="return",
            refund_type="full",
            refund_method="cash",
            created_at=datetime.now(),
            requested_by_id=cashier.id,
        )
    )
    db_session.commit()
    tok = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    r = client.get("/api/overview/summary", headers=_auth(tok))
    assert r.status_code == 200
    assert r.json()["summary"]["revenue"] == 0.0
    assert r.json()["summary"]["refunds"] == 5.0


def test_overview_stock_counts(client, db_session):
    _seed_users(db_session)
    db_session.add(StoreSettings(store_name="Stock Shop", default_low_stock_threshold=10))
    db_session.add_all(
        [
            Product(
                name="Out",
                stock_qty=0,
                cost_price=Decimal("1"),
                selling_price=Decimal("2"),
                is_active=True,
            ),
            Product(
                name="Low",
                stock_qty=3,
                cost_price=Decimal("1"),
                selling_price=Decimal("2"),
                is_active=True,
                low_stock_threshold=5,
            ),
            Product(
                name="Ok",
                stock_qty=100,
                cost_price=Decimal("1"),
                selling_price=Decimal("2"),
                is_active=True,
            ),
        ]
    )
    db_session.commit()
    tok = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    data = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert data["summary"]["out_of_stock_count"] == 1
    assert data["summary"]["low_stock_count"] == 1
    inv = {i["label"]: i["count"] for i in data["inventory_status"]}
    assert inv["Out of stock"] == 1
    assert inv["Low stock"] == 1
    assert inv["Healthy"] == 1


def test_overview_tenant_isolation(client, db_session):
    t1 = Tenant(tenant_uid="t-ov-1", name="Biz A")
    t2 = Tenant(tenant_uid="t-ov-2", name="Biz B")
    db_session.add_all([t1, t2])
    db_session.flush()
    _seed_users(db_session, tenant_a=t1.id, tenant_b=t2.id)
    admin_a = db_session.query(User).filter_by(username="ov_admin").one()
    admin_b = db_session.query(User).filter_by(username="ov_other_admin").one()
    cash_a = db_session.query(User).filter_by(username="ov_cashier").one()

    p_a = Product(
        name="A Only",
        stock_qty=5,
        cost_price=Decimal("1"),
        selling_price=Decimal("10"),
        is_active=True,
        tenant_id=t1.id,
    )
    p_b = Product(
        name="B Only",
        stock_qty=5,
        cost_price=Decimal("1"),
        selling_price=Decimal("10"),
        is_active=True,
        tenant_id=t2.id,
    )
    db_session.add_all([p_a, p_b])
    db_session.flush()
    sale_b = Sale(
        created_at=datetime.now(),
        cashier_id=admin_b.id,
        subtotal=Decimal("10"),
        discount_total=Decimal("0"),
        total=Decimal("10"),
        tenant_id=t2.id,
    )
    db_session.add(sale_b)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale_b.id,
            product_id=p_b.id,
            quantity=1,
            unit_price=Decimal("10"),
            discount=Decimal("0"),
            line_total=Decimal("10"),
        )
    )
    db_session.commit()

    tok_a = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    data = client.get("/api/overview/summary", headers=_auth(tok_a)).json()
    assert data["summary"]["completed_sales"] == 0
    assert data["summary"]["revenue"] == 0
    names = [c["label"] for c in data.get("top_products", [])]
    assert "B Only" not in names


def test_overview_branch_filter(client, db_session):
    t = Tenant(tenant_uid="t-br", name="Branch Biz")
    db_session.add(t)
    db_session.flush()
    b1 = Branch(tenant_id=t.id, name="North", is_active=True)
    b2 = Branch(tenant_id=t.id, name="South", is_active=True)
    db_session.add_all([b1, b2])
    db_session.flush()
    admin = User(
        username="br_admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
        tenant_id=t.id,
    )
    db_session.add(admin)
    db_session.flush()
    product = Product(
        name="Branch Item",
        stock_qty=20,
        cost_price=Decimal("2"),
        selling_price=Decimal("8"),
        is_active=True,
        tenant_id=t.id,
    )
    db_session.add(product)
    db_session.flush()
    for branch, total in ((b1, Decimal("8")), (b2, Decimal("16"))):
        sale = Sale(
            created_at=datetime.now(),
            cashier_id=admin.id,
            subtotal=total,
            discount_total=Decimal("0"),
            total=total,
            tenant_id=t.id,
            branch_id=branch.id,
        )
        db_session.add(sale)
        db_session.flush()
        qty = int(total / 8)
        db_session.add(
            SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                quantity=qty,
                unit_price=Decimal("8"),
                discount=Decimal("0"),
                line_total=total,
            )
        )
    db_session.commit()

    tok = _login(client, "br_admin", "AdminPass1234")["access_token"]
    all_data = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert all_data["summary"]["completed_sales"] == 2
    assert all_data["summary"]["revenue"] == 24.0

    north = client.get(
        "/api/overview/summary",
        params={"branch_id": b1.id},
        headers=_auth(tok),
    ).json()
    assert north["summary"]["completed_sales"] == 1
    assert north["summary"]["revenue"] == 8.0
    assert north["business"]["branch_name"] == "North"

    bad = client.get(
        "/api/overview/summary",
        params={"branch_id": 99999},
        headers=_auth(tok),
    )
    assert bad.status_code == 400


def test_supervisor_can_call_overview_api(client, db_session):
    _seed_users(db_session)
    tok = _login(client, "ov_supervisor", "SuperPass1234")["access_token"]
    r = client.get("/api/overview/summary", headers=_auth(tok))
    assert r.status_code == 200


def test_outstanding_credit_card(client, db_session):
    _seed_users(db_session)
    db_session.add(
        Customer(name="Owes", credit_balance=Decimal("42.50"), phone="1")
    )
    db_session.commit()
    tok = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    data = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert data["summary"]["outstanding_credit"] == 42.5


def test_role_permissions_js_admin_lands_on_overview():
    """Cashier regression: JS resolver must keep cashiers on POS."""
    path = os.path.join(
        os.path.dirname(__file__), "..", "static", "js", "role-permissions.js"
    )
    src = open(path, encoding="utf-8").read()
    assert "return '/overview'" in src
    assert "function postLoginPath" in src
    # Cashiers fall through to '/'
    assert "return '/'" in src


def test_overview_js_uses_summary_api():
    path = os.path.join(
        os.path.dirname(__file__), "..", "static", "js", "overview.js"
    )
    src = open(path, encoding="utf-8").read()
    assert "/api/overview/summary" in src
    assert "ov-retry" in src
    assert "view_reports" in src


def test_cashier_pos_route_unchanged_markers(client, db_session):
    """Selling page markers must remain on index (no dashboard swap)."""
    html = client.get("/").text
    assert "pos-screen" in html or "id=\"pos-screen\"" in html or "login-screen" in html
    assert "overview.js" not in html
    assert "overview.css" not in html


def test_overview_action_button_labels_and_classes(client, db_session):
    """Dark action controls must keep visible text labels + semantic classes."""
    _seed_users(db_session)
    _login(client, "ov_admin", "AdminPass1234")
    html = client.get("/overview").text
    assert "overview-button-primary" in html
    assert "overview-button-danger" in html
    assert "Open POS" in html
    assert "Inventory" in html
    assert "Refresh" in html
    assert "Log out" in html
    assert html.count('href="/?pos=1"') >= 2
    assert 'id="ov-refresh"' in html
    assert 'id="ov-logout"' in html
    assert "overview.css?v=11" in html
    assert "page-overview" in html
    assert "ov-fab-toggle" in html
    assert "Management" in html
    assert html.count('href="/admin"') == 1
    assert "style.css" in html
    assert html.index("style.css") < html.index("overview.css")


def test_overview_css_primary_button_contrast():
    path = os.path.join(
        os.path.dirname(__file__), "..", "static", "css", "overview.css"
    )
    css = open(path, encoding="utf-8").read()
    assert "overview-button-primary" in css
    assert "overview-button-danger" in css
    assert "color: #ffffff !important" in css
    assert "#667eea" in css
    assert "background: #c75050 !important" in css
    assert ":not(.overview-button)" in css
    assert "flex-direction: column !important" in css


def test_overview_js_refresh_and_local_today():
    path = os.path.join(
        os.path.dirname(__file__), "..", "static", "js", "overview.js"
    )
    src = open(path, encoding="utf-8").read()
    assert "ov-refresh" in src
    assert "addEventListener('click', loadDashboard)" in src
    assert "localDateISO" in src
    assert "getFullYear()" in src
    assert "getMonth()" in src
    assert "getDate()" in src
    assert "ov-card-cash-on-hand" in src
    assert "function todayISO()" in src
    today_fn = src.split("function todayISO()")[1].split("function ")[0]
    assert "toISOString()" not in today_fn
    assert "localDateISO" in today_fn


def test_cash_on_hand_cash_sale_increases(client, db_session):
    admin, cashier, _ = _seed_users(db_session)
    product = Product(
        name="Cash Item",
        stock_qty=20,
        cost_price=Decimal("2"),
        selling_price=Decimal("10"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    sale = Sale(
        created_at=datetime.now(),
        cashier_id=cashier.id,
        subtotal=Decimal("10"),
        discount_total=Decimal("0"),
        total=Decimal("10"),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=1,
            unit_price=Decimal("10"),
            discount=Decimal("0"),
            line_total=Decimal("10"),
        )
    )
    db_session.add(Payment(sale_id=sale.id, method="cash", amount=Decimal("10")))
    db_session.commit()
    tok = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    data = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert data["summary"]["cash_on_hand"] == 10.0
    assert data["summary"]["cash_payments"] == 10.0
    card = next(c for c in data["cards"] if c["key"] == "cash_on_hand")
    assert card["label"] == "Cash on hand"
    assert card["value"] == 10.0


def test_cash_on_hand_card_payment_excluded(client, db_session):
    admin, cashier, _ = _seed_users(db_session)
    product = Product(
        name="Card Item",
        stock_qty=20,
        cost_price=Decimal("2"),
        selling_price=Decimal("15"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    sale = Sale(
        created_at=datetime.now(),
        cashier_id=cashier.id,
        subtotal=Decimal("15"),
        discount_total=Decimal("0"),
        total=Decimal("15"),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=1,
            unit_price=Decimal("15"),
            discount=Decimal("0"),
            line_total=Decimal("15"),
        )
    )
    db_session.add(Payment(sale_id=sale.id, method="card", amount=Decimal("15")))
    db_session.commit()
    tok = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    data = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert data["summary"]["cash_on_hand"] == 0.0
    assert data["summary"]["revenue"] == 15.0


def test_cash_on_hand_refund_and_withdrawal_reduce(client, db_session):
    admin, cashier, _ = _seed_users(db_session)
    product = Product(
        name="Till Item",
        stock_qty=20,
        cost_price=Decimal("1"),
        selling_price=Decimal("20"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    sale = Sale(
        created_at=datetime.now(),
        cashier_id=cashier.id,
        subtotal=Decimal("20"),
        discount_total=Decimal("0"),
        total=Decimal("20"),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=1,
            unit_price=Decimal("20"),
            discount=Decimal("0"),
            line_total=Decimal("20"),
        )
    )
    db_session.add(Payment(sale_id=sale.id, method="cash", amount=Decimal("20")))
    db_session.add(
        Refund(
            sale_id=sale.id,
            refund_number="RF-CASH-1",
            amount=Decimal("5"),
            status="approved",
            reason="partial",
            refund_type="partial",
            refund_method="cash",
            created_at=datetime.now(),
            requested_by_id=cashier.id,
        )
    )
    db_session.add(
        Withdrawal(
            cashier_id=admin.id,
            amount=Decimal("3"),
            reason="Float pull",
            created_at=datetime.now(),
        )
    )
    db_session.commit()
    tok = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    data = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert data["summary"]["cash_on_hand"] == 12.0
    assert data["summary"]["cash_refunds"] == 5.0
    assert data["summary"]["withdrawals_total"] == 3.0


def test_cash_on_hand_matches_reports_summary(client, db_session):
    admin, cashier, _ = _seed_users(db_session)
    product = Product(
        name="Sync Item",
        stock_qty=10,
        cost_price=Decimal("1"),
        selling_price=Decimal("8"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    sale = Sale(
        created_at=datetime.now(),
        cashier_id=cashier.id,
        subtotal=Decimal("8"),
        discount_total=Decimal("0"),
        total=Decimal("8"),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=1,
            unit_price=Decimal("8"),
            discount=Decimal("0"),
            line_total=Decimal("8"),
        )
    )
    db_session.add(Payment(sale_id=sale.id, method="cash", amount=Decimal("8")))
    db_session.add(
        Withdrawal(
            cashier_id=admin.id,
            amount=Decimal("2"),
            reason="Expense",
            created_at=datetime.now(),
        )
    )
    db_session.commit()
    tok = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    today = date.today().isoformat()
    ov = client.get("/api/overview/summary", headers=_auth(tok)).json()
    rp = client.get(
        "/api/reports/summary",
        params={"from_date": today, "to_date": today},
        headers=_auth(tok),
    )
    assert rp.status_code == 200
    assert ov["summary"]["cash_on_hand"] == float(rp.json()["cash_on_hand"])


def test_cash_on_hand_tenant_isolation(client, db_session):
    t1 = Tenant(tenant_uid="t-cash-1", name="Cash A")
    t2 = Tenant(tenant_uid="t-cash-2", name="Cash B")
    db_session.add_all([t1, t2])
    db_session.flush()
    _seed_users(db_session, tenant_a=t1.id, tenant_b=t2.id)
    admin_b = db_session.query(User).filter_by(username="ov_other_admin").one()
    p_b = Product(
        name="B Cash",
        stock_qty=5,
        cost_price=Decimal("1"),
        selling_price=Decimal("50"),
        is_active=True,
        tenant_id=t2.id,
    )
    db_session.add(p_b)
    db_session.flush()
    sale_b = Sale(
        created_at=datetime.now(),
        cashier_id=admin_b.id,
        subtotal=Decimal("50"),
        discount_total=Decimal("0"),
        total=Decimal("50"),
        tenant_id=t2.id,
    )
    db_session.add(sale_b)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale_b.id,
            product_id=p_b.id,
            quantity=1,
            unit_price=Decimal("50"),
            discount=Decimal("0"),
            line_total=Decimal("50"),
        )
    )
    db_session.add(Payment(sale_id=sale_b.id, method="cash", amount=Decimal("50")))
    db_session.commit()
    tok_a = _login(client, "ov_admin", "AdminPass1234")["access_token"]
    data = client.get("/api/overview/summary", headers=_auth(tok_a)).json()
    assert data["summary"]["cash_on_hand"] == 0.0


def test_cash_on_hand_branch_excludes_other_branch_cash(client, db_session):
    t = Tenant(tenant_uid="t-cash-br", name="Cash Branch Biz")
    db_session.add(t)
    db_session.flush()
    b1 = Branch(tenant_id=t.id, name="North Till", is_active=True)
    b2 = Branch(tenant_id=t.id, name="South Till", is_active=True)
    db_session.add_all([b1, b2])
    db_session.flush()
    admin = User(
        username="cash_br_admin",
        password_hash=_hash("AdminPass1234"),
        role="admin",
        is_active=True,
        tenant_id=t.id,
    )
    db_session.add(admin)
    db_session.flush()
    product = Product(
        name="Branch Cash Item",
        stock_qty=20,
        cost_price=Decimal("1"),
        selling_price=Decimal("10"),
        is_active=True,
        tenant_id=t.id,
    )
    db_session.add(product)
    db_session.flush()
    for branch, amt in ((b1, Decimal("10")), (b2, Decimal("30"))):
        sale = Sale(
            created_at=datetime.now(),
            cashier_id=admin.id,
            subtotal=amt,
            discount_total=Decimal("0"),
            total=amt,
            tenant_id=t.id,
            branch_id=branch.id,
        )
        db_session.add(sale)
        db_session.flush()
        db_session.add(
            SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                quantity=1,
                unit_price=amt,
                discount=Decimal("0"),
                line_total=amt,
            )
        )
        db_session.add(Payment(sale_id=sale.id, method="cash", amount=amt))
    db_session.commit()
    tok = _login(client, "cash_br_admin", "AdminPass1234")["access_token"]
    all_data = client.get("/api/overview/summary", headers=_auth(tok)).json()
    assert all_data["summary"]["cash_on_hand"] == 40.0
    assert all_data["cash_on_hand_meta"]["withdrawals_included"] is True
    north = client.get(
        "/api/overview/summary",
        params={"branch_id": b1.id},
        headers=_auth(tok),
    ).json()
    assert north["summary"]["cash_on_hand"] is None
    assert north["cash_on_hand_meta"]["scope"] == "branch"
    assert north["cash_on_hand_meta"]["available"] is False
    assert north["cash_on_hand_meta"]["withdrawals_included"] is False
    assert "Withdrawals" in (north["cash_on_hand_meta"].get("reason") or "")
    cash_card = next(c for c in north["cards"] if c["key"] == "cash_on_hand")
    assert cash_card["available"] is False
    assert cash_card["value"] is None
    assert cash_card["display"] == "Unavailable"


def test_style_css_excludes_overview_from_white_text():
    path = os.path.join(
        os.path.dirname(__file__), "..", "static", "css", "style.css"
    )
    css = open(path, encoding="utf-8").read()
    assert ":not(.page-overview):not(.overview-page)" in css
