"""Stock Transfers UI contracts: page gating, template markers, JS wiring,
service-worker network-only policy, navigation entries, and additive API fields.

Follows the repo convention of static-file contract tests (like test_settings_ui
and test_client_build_cache) plus page-route integration tests.
"""
from __future__ import annotations

import os
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
TEMPLATE = (ROOT / "templates" / "stock_transfers.html").read_text(encoding="utf-8")
PAGE_JS = (ROOT / "static" / "js" / "stock-transfers.js").read_text(encoding="utf-8")
SW_JS = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
ADMIN_HTML = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
OVERVIEW_HTML = (ROOT / "templates" / "overview.html").read_text(encoding="utf-8")
OVERVIEW_JS = (ROOT / "static" / "js" / "overview.js").read_text(encoding="utf-8")


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


def _user(db, username, role):
    u = User(
        username=username,
        password_hash=_hash("AdminPass1234"),
        role=role,
        is_active=True,
    )
    db.add(u)
    db.flush()
    return u


def _login(client: TestClient, username: str) -> str:
    """Log in and return the bearer access token (also sets the session cookie)."""
    r = client.post(
        "/api/auth/token",
        data={"username": username, "password": "AdminPass1234"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# --- page route gating -------------------------------------------------------


def test_stock_transfers_page_redirects_unauthenticated(client):
    r = client.get("/stock-transfers", follow_redirects=False)
    assert r.status_code in (303, 307)
    loc = r.headers.get("location", "")
    assert "/?next=/stock-transfers" in loc


def test_stock_transfers_page_redirects_cashier(client, db_session):
    _user(db_session, "st_cashier", "cashier")
    db_session.commit()
    _login(client, "st_cashier")
    r = client.get("/stock-transfers", follow_redirects=False)
    # Cashier has no BRANCH_TRANSFER_VIEW -> redirected to their landing page.
    assert r.status_code == 303
    assert r.headers.get("location", "") != ""
    assert "stock-transfers" not in r.headers.get("location", "")


def test_stock_transfers_page_ok_for_admin(client, db_session):
    _user(db_session, "st_admin", "admin")
    db_session.commit()
    _login(client, "st_admin")
    r = client.get("/stock-transfers")
    assert r.status_code == 200
    assert "Stock Transfers" in r.text
    assert "stock-transfers.js" in r.text


def test_stock_transfers_page_ok_for_supervisor(client, db_session):
    _user(db_session, "st_supervisor", "supervisor")
    db_session.commit()
    _login(client, "st_supervisor")
    r = client.get("/stock-transfers")
    assert r.status_code == 200
    assert "stock-transfers.js" in r.text

# --- template contract -------------------------------------------------------


def test_template_has_all_required_ui_markers():
    for marker in (
        'id="btn-new-transfer"',
        'id="filter-status"',
        'id="filter-from"',
        'id="filter-to"',
        'id="transfer-search"',
        'id="btn-refresh"',
        'id="transfers-body"',
        'id="transfers-mobile"',
        'id="transfers-empty"',
        'id="pagination"',
        'id="detail-modal"',
        'id="create-modal"',
        'id="confirm-modal"',
        'id="toast-wrap"',
        'id="create-from"',
        'id="create-to"',
        'id="create-notes"',
        'id="create-product-q"',
        'id="btn-create-save"',
    ):
        assert marker in TEMPLATE, f"missing template marker: {marker}"


def test_template_loads_page_script_with_build_stamp():
    assert "stock-transfers.js?v={{ pos_build }}" in TEMPLATE
    assert 'name="pos-build"' in TEMPLATE
    assert "theme-instant.js" in TEMPLATE


def test_template_has_mobile_layout():
    assert "@media (max-width: 768px)" in TEMPLATE
    assert 'id="transfers-mobile"' in TEMPLATE
    assert "xfer-mobile" in TEMPLATE


def test_template_uses_escape_never_raw_undefined():
    # The page must never render 'undefined' / '[object Object]'.
    assert "undefined" not in TEMPLATE
    assert "[object Object]" not in PAGE_JS
    assert "document.createElement('div')" in PAGE_JS  # esc() helper


# --- JS wiring contract ------------------------------------------------------


def test_page_js_sends_bearer_token_from_pos_token():
    assert "localStorage.getItem('pos_token')" in PAGE_JS
    assert "Authorization" in PAGE_JS
    assert "Bearer " in PAGE_JS
    assert "'/api/auth/me'" in PAGE_JS


def test_page_js_handles_401_redirect():
    assert "res.status === 401" in PAGE_JS
    assert "localStorage.removeItem('pos_token')" in PAGE_JS
    assert "window.location.replace('/')" in PAGE_JS


def test_page_js_handles_403_permission_message():
    assert "403" in PAGE_JS
    assert "permission" in PAGE_JS.lower()


def test_page_js_handles_409_conflict():
    assert "409" in PAGE_JS


def test_page_js_wires_exact_transfer_endpoints():
    # All lifecycle/item action URLs are built from the /api/transfers prefix.
    assert "'/api/transfers?'" in PAGE_JS
    assert "'/api/transfers/' + encodeURIComponent(" in PAGE_JS
    for suffix in ("'/request'", "'/approve'", "'/reject'", "'/cancel'", "'/dispatch'", "'/receive'", "'/items'"):
        assert suffix in PAGE_JS, f"missing JS wiring for action: {suffix}"
    assert "'/api/products?q=' + encodeURIComponent(q) + '&limit=12&skip_total=1'" in PAGE_JS
    assert "'/api/branches'" in PAGE_JS
    assert "method: 'DELETE'" in PAGE_JS  # draft deletion route


def test_page_js_has_lifecycle_status_badges():
    for status in ("draft", "requested", "approved", "dispatched", "in_transit", "received", "rejected", "cancelled"):
        assert status in PAGE_JS, f"missing status: {status}"


def test_page_js_gates_actions_by_permission():
    for perm in (
        "'branch.transfer.view'",
        "'branch.transfer.create'",
        "'branch.transfer.request'",
        "'branch.transfer.approve'",
        "'branch.transfer.reject'",
        "'branch.transfer.cancel'",
        "'branch.transfer.dispatch'",
        "'branch.transfer.receive'",
    ):
        assert perm in PAGE_JS, f"missing permission gate: {perm}"


def test_page_js_idempotency_keys():
    assert "client_transfer_id" in PAGE_JS
    assert "client_movement_id" in PAGE_JS
    assert "'xfer-' + uuid()" in PAGE_JS
    assert "'recv-' + uuid()" in PAGE_JS


def test_page_js_branch_safety_validations():
    assert "Source and destination branches must be different" in PAGE_JS
    assert "already on the transfer" in PAGE_JS  # duplicate product line blocked
    assert "cannot exceed the remaining dispatched" in PAGE_JS  # receive constraint


def test_page_js_double_submit_guard():
    assert "busy" in PAGE_JS
    assert "disabled = true" in PAGE_JS


# --- service worker contract -------------------------------------------------


def test_sw_bumps_cache_version():
    assert "pos-sw-v4-transfers-network-only" in SW_JS


def test_sw_network_only_for_transfers():
    assert "NETWORK_ONLY_API_PREFIXES" in SW_JS
    assert "'/api/transfers'" in SW_JS
    assert "cache: 'no-store'" in SW_JS
    # Transfers must never be routed to a cache-backed response.
    assert "caches.match" not in SW_JS.split("fetch")[-1]


def test_sw_keeps_password_reset_isolation():
    assert "isPasswordResetRequest" in SW_JS
    assert "'/reset-password'" in SW_JS


# --- navigation contract -----------------------------------------------------


def test_admin_page_links_to_stock_transfers():
    assert "/stock-transfers" in ADMIN_HTML
    assert 'id="btn-stock-transfers"' in ADMIN_HTML


def test_overview_page_links_to_stock_transfers_gated():
    assert 'data-perm="transfers"' in OVERVIEW_HTML
    assert 'href="/stock-transfers"' in OVERVIEW_HTML
    assert "else if (need === 'transfers') show = hasPerm('branch.transfer.view');" in OVERVIEW_JS


# --- additive API fields -----------------------------------------------------


def test_transfer_dict_includes_version_and_actor_names(client, db_session):
    from app.enterprise_models import Branch, StockTransfer

    admin = _user(db_session, "st_fields_admin", "admin")
    main = Branch(name="Main", code="MAIN", is_default=True, is_active=True, tenant_id=None)
    west = Branch(name="West", code="WEST", is_active=True, tenant_id=None)
    db_session.add_all([main, west])
    db_session.flush()
    db_session.commit()
    tok = _login(client, "st_fields_admin")

    t = StockTransfer(
        tenant_id=None,
        transfer_number="TR-TEST-0001",
        from_branch_id=main.id,
        to_branch_id=west.id,
        status="draft",
        created_by=admin.id,
    )
    db_session.add(t)
    db_session.commit()

    r = client.get("/api/transfers", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    row = body[0]
    assert "version" in row
    assert row["created_by_name"] == "st_fields_admin"
    assert row["created_by"] == admin.id


def test_products_endpoint_exposes_branch_reserved_and_available(client, db_session):
    from app.enterprise_models import Branch, BranchProductStock
    from app.models import Product

    admin = _user(db_session, "st_prod_admin", "admin")
    main = Branch(name="Main", code="MAIN", is_default=True, is_active=True, tenant_id=None)
    db_session.add(main)
    db_session.flush()
    p = Product(
        name="Test Widget",
        barcode="TST-123",
        selling_price=10,
        cost_price=4,
        stock_qty=0,
        is_active=True,
    )
    db_session.add(p)
    db_session.flush()
    db_session.add(
        BranchProductStock(
            branch_id=main.id, product_id=p.id, stock_qty=10, reserved_qty=3, tenant_id=None
        )
    )
    db_session.commit()

    tok = _login(client, "st_prod_admin")
    r = client.get(
        "/api/products?q=Test&limit=10",
        headers={"Authorization": "Bearer " + tok, "X-Branch-Id": str(main.id)},
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    row = rows[0]
    assert row["stockQty"] == "10.0000"
    assert row["reservedQty"] == "3.0000"
    assert row["availableQty"] == "7.0000"


# --- additional UI contract tests (production-readiness) ---------------------


def test_transfer_list_returns_empty_200_for_admin(client, db_session):
    """Requirement: the list loads an empty 200 response for an authorized user."""
    _user(db_session, "st_empty_admin", "admin")
    db_session.commit()
    tok = _login(client, "st_empty_admin")
    r = client.get("/api/transfers", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200
    assert r.json() == []


def test_stock_transfers_page_ok_for_owner(client, db_session):
    """Requirement: navigation/access works for the owner role too."""
    _user(db_session, "st_owner", "owner")
    db_session.commit()
    _login(client, "st_owner")
    r = client.get("/stock-transfers")
    assert r.status_code == 200
    assert "stock-transfers.js" in r.text


def test_page_js_builds_exact_create_payload():
    """Requirement: draft creation sends the exact backend TransferCreateIn payload."""
    assert "from_branch_id: Number(fromVal)" in PAGE_JS
    assert "to_branch_id: Number(toVal)" in PAGE_JS
    assert "notes: $('create-notes').value || null" in PAGE_JS
    assert "items: items" in PAGE_JS
    assert "client_transfer_id: createClientTransferId" in PAGE_JS
    assert "method: 'POST'" in PAGE_JS


def test_page_js_requires_positive_item_quantity():
    """Requirement: product quantities must be positive (backend stays authoritative)."""
    assert "must be a positive number" in PAGE_JS


def test_page_js_renders_escaped_never_undefined_fields():
    """Requirement: list/detail rendering escapes fields and never shows raw nulls."""
    assert "esc(t.transfer_number" in PAGE_JS
    assert "esc(branchName(" in PAGE_JS
    assert "esc(t.created_by_name" in PAGE_JS
    assert "fmtQty(sumQty(t.items, 'quantity_requested'))" in PAGE_JS
    assert "esc(row[0])" in PAGE_JS  # detail kv keys escaped
    assert "esc(row[1])" in PAGE_JS  # detail kv values escaped


def test_page_js_gates_request_action_to_draft_state():
    """Requirement: the Request action appears only in the valid draft state."""
    idx_draft = PAGE_JS.index("if (st === 'draft') {")
    idx_requested = PAGE_JS.index("} else if (st === 'requested') {")
    draft_block = PAGE_JS[idx_draft:idx_requested]
    assert "'Request'" in draft_block
    assert "hasPerm(PERMS.REQUEST)" in draft_block
    # No later lifecycle state may offer the request action.
    assert "kind: 'request'" not in PAGE_JS[idx_requested:]


def test_page_js_gates_approve_action_to_requested_state_and_permission():
    """Requirement: Approve is permission and state gated (requested only)."""
    idx_requested = PAGE_JS.index("} else if (st === 'requested') {")
    idx_approved = PAGE_JS.index("} else if (st === 'approved') {")
    block = PAGE_JS[idx_requested:idx_approved]
    assert "'Approve'" in block
    assert "hasPerm(PERMS.APPROVE)" in block


def test_page_js_reject_requires_reason():
    """Requirement: rejecting requires a reason before submission."""
    assert "A rejection reason is required." in PAGE_JS
    assert "JSON.stringify({ reason: reason })" in PAGE_JS


def test_page_js_cancel_unavailable_after_dispatch():
    """Requirement: cancellation is never offered once stock is dispatched."""
    idx_dispatched = PAGE_JS.index("} else if (st === 'dispatched'")
    rest = PAGE_JS[idx_dispatched:]
    assert "kind: 'cancel'" not in rest
    assert "'Cancel'" not in rest
    # Approved-state cancel is still guarded against dispatched quantities.
    assert "!hasDispatchedQty(t)" in PAGE_JS


def test_page_js_dispatch_prevents_double_submission():
    """Requirement: dispatch disables the confirm button while a request is pending."""
    assert "okBtn.disabled = true;" in PAGE_JS
    assert "okBtn.disabled = false;" in PAGE_JS
    assert "busy" in PAGE_JS
    assert "'/dispatch'" in PAGE_JS


def test_page_js_receive_describes_only_accepted_as_destination_stock():
    """Requirement: only the accepted quantity is described as destination stock."""
    assert "Only the ACCEPTED quantity enters the destination branch available stock" in PAGE_JS
    assert "accepted + damaged + missing > max" in PAGE_JS


def test_page_js_uses_no_global_admin_dependency():
    """The page must not depend on adminApi unless it loads admin.js itself."""
    assert "adminApi" not in PAGE_JS


def test_page_js_deletes_removed_lines_when_editing_draft():
    """Editing a draft must delete backend lines the user removed (line removal)."""
    assert "editOriginalItemIds" in PAGE_JS
    assert "Delete lines the user removed while editing the draft." in PAGE_JS
    # The same DELETE /items/{item_id} route used for removal while editing.
    assert "/items/' + encodeURIComponent(oldId)" in PAGE_JS
    assert "method: 'DELETE'" in PAGE_JS

