"""Receipt Design settings API + render helpers."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from types import SimpleNamespace

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
from app.receipt_design import (
    DEFAULT_RECEIPT_FOOTER,
    DEFAULT_RECEIPT_KEEP_FOR_REFUND,
    MAX_RECEIPT_PHONES,
    compose_sale_receipt_closing,
    receipt_phones_from_settings,
    resolve_keep_for_refund_text,
    resolve_receipt_footer,
    validate_receipt_phones,
)


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


def _seed_admin(db_session, *, username="rd_admin", password="AdminPass1234"):
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name="Receipt Admin",
        password_hash=_hash(password),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.add(StoreSettings(store_name="Receipt Shop", store_phone="0711000000"))
    db_session.commit()
    db_session.refresh(user)
    return user


def _login(client, username="rd_admin", password="AdminPass1234"):
    r = client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_resolve_defaults_when_unset():
    assert resolve_keep_for_refund_text(None) == DEFAULT_RECEIPT_KEEP_FOR_REFUND
    assert resolve_receipt_footer(None) == DEFAULT_RECEIPT_FOOTER
    s = SimpleNamespace(
        receipt_keep_for_refund_text=None,
        receipt_footer=None,
        receipt_phone_1=None,
        receipt_phone_2=None,
        receipt_phone_3=None,
    )
    assert resolve_keep_for_refund_text(s) == DEFAULT_RECEIPT_KEEP_FOR_REFUND
    assert resolve_receipt_footer(s) == DEFAULT_RECEIPT_FOOTER
    closing = compose_sale_receipt_closing(s)
    assert DEFAULT_RECEIPT_KEEP_FOR_REFUND in closing
    assert DEFAULT_RECEIPT_FOOTER in closing
    assert "Phone:" not in closing


def test_resolve_empty_hides_sections():
    s = SimpleNamespace(
        receipt_keep_for_refund_text="",
        receipt_footer="",
        receipt_phone_1="",
        receipt_phone_2=None,
        receipt_phone_3="  ",
    )
    assert resolve_keep_for_refund_text(s) is None
    assert resolve_receipt_footer(s) is None
    assert receipt_phones_from_settings(s) == []
    assert compose_sale_receipt_closing(s) == ""


def test_custom_footer_preserves_line_breaks():
    s = SimpleNamespace(
        receipt_keep_for_refund_text="Please keep this receipt.",
        receipt_footer="Line one\nLine two\nLine three",
        receipt_phone_1="0712 345 678",
        receipt_phone_2="0773 456 789",
        receipt_phone_3=None,
    )
    footer = resolve_receipt_footer(s)
    assert footer == "Line one\nLine two\nLine three"
    phones = receipt_phones_from_settings(s)
    assert phones == ["0712 345 678", "0773 456 789"]
    closing = compose_sale_receipt_closing(s)
    assert "Please keep this receipt." in closing
    assert "Phone:\n0712 345 678\n0773 456 789" in closing
    assert "Line one\nLine two\nLine three" in closing
    assert closing.count("Phone:") == 1


def test_three_phones_max_and_blank_skipped():
    s = SimpleNamespace(
        receipt_keep_for_refund_text=None,
        receipt_footer=None,
        receipt_phone_1="111",
        receipt_phone_2="",
        receipt_phone_3="333",
    )
    assert receipt_phones_from_settings(s) == ["111", "333"]
    with pytest.raises(ValueError):
        validate_receipt_phones(["1", "2", "3", "4"])
    assert len(validate_receipt_phones(["a", None, "c"])) == MAX_RECEIPT_PHONES


def test_admin_can_save_and_retrieve_receipt_settings(client, db_session):
    _seed_admin(db_session)
    tok = _login(client)["access_token"]
    payload = {
        "store_name": "Receipt Shop",
        "store_phone": "0711000000",
        "low_stock_email_enabled": False,
        "default_low_stock_threshold": 10,
        "currency": "USD",
        "receipt_keep_for_refund_text": "Please keep your receipt for returns.",
        "receipt_footer": "Thanks!\nCome again.",
        "receipt_phone_1": "0712 345 678",
        "receipt_phone_2": "0773 456 789",
        "receipt_phone_3": "0784 567 890",
    }
    put = client.put("/api/store-settings", headers=_auth(tok), json=payload)
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["receipt_keep_for_refund_text"] == "Please keep your receipt for returns."
    assert body["receipt_footer"] == "Thanks!\nCome again."
    assert body["receipt_phone_1"] == "0712 345 678"
    assert body["receipt_phone_2"] == "0773 456 789"
    assert body["receipt_phone_3"] == "0784 567 890"

    got = client.get("/api/store-settings", headers=_auth(tok))
    assert got.status_code == 200
    again = got.json()
    assert again["receipt_footer"] == "Thanks!\nCome again."
    assert again["receipt_phone_3"] == "0784 567 890"


def test_blank_optional_phones_and_footer_persist(client, db_session):
    _seed_admin(db_session)
    tok = _login(client)["access_token"]
    put = client.put(
        "/api/store-settings",
        headers=_auth(tok),
        json={
            "store_name": "Receipt Shop",
            "low_stock_email_enabled": False,
            "default_low_stock_threshold": 10,
            "receipt_keep_for_refund_text": "",
            "receipt_footer": "",
            "receipt_phone_1": "0712",
            "receipt_phone_2": "",
            "receipt_phone_3": None,
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["receipt_keep_for_refund_text"] == ""
    assert body["receipt_footer"] == ""
    assert body["receipt_phone_1"] == "0712"
    assert body["receipt_phone_2"] in (None, "")
    assert body["receipt_phone_3"] in (None, "")


def test_receipt_phones_list_over_three_rejected(client, db_session):
    _seed_admin(db_session)
    tok = _login(client)["access_token"]
    put = client.put(
        "/api/store-settings",
        headers=_auth(tok),
        json={
            "store_name": "Receipt Shop",
            "low_stock_email_enabled": False,
            "default_low_stock_threshold": 10,
            "receipt_phones": ["1", "2", "3", "4"],
        },
    )
    assert put.status_code == 400
    assert "3" in (put.json().get("detail") or "")


def test_cashier_cannot_modify_receipt_settings(client, db_session):
    _seed_admin(db_session)
    db_session.add(
        User(
            username="rd_cashier",
            email="rd_cashier@example.com",
            password_hash=_hash("CashPass1234"),
            role="cashier",
            is_active=True,
        )
    )
    db_session.commit()
    tok = _login(client, "rd_cashier", "CashPass1234")["access_token"]
    put = client.put(
        "/api/store-settings",
        headers=_auth(tok),
        json={
            "store_name": "Hacked",
            "low_stock_email_enabled": False,
            "default_low_stock_threshold": 10,
            "receipt_footer": "nope",
        },
    )
    assert put.status_code in (401, 403)


def test_currency_update_without_receipt_fields_preserves_design(client, db_session):
    _seed_admin(db_session)
    tok = _login(client)["access_token"]
    client.put(
        "/api/store-settings",
        headers=_auth(tok),
        json={
            "store_name": "Receipt Shop",
            "low_stock_email_enabled": False,
            "default_low_stock_threshold": 10,
            "receipt_footer": "Keep me",
            "receipt_phone_1": "0999",
        },
    )
    put = client.put(
        "/api/store-settings",
        headers=_auth(tok),
        json={
            "store_name": "Receipt Shop",
            "currency": "ZAR",
            "low_stock_email_enabled": False,
            "default_low_stock_threshold": 10,
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["currency"] == "ZAR"
    assert body["receipt_footer"] == "Keep me"
    assert body["receipt_phone_1"] == "0999"


def test_receipt_settings_tenant_scoped(client, db_session):
    t1 = Tenant(name="T1 Co", tenant_uid=str(uuid.uuid4()))
    t2 = Tenant(name="T2 Co", tenant_uid=str(uuid.uuid4()))
    db_session.add_all([t1, t2])
    db_session.flush()
    db_session.add_all(
        [
            User(
                username="rd_a1",
                email="a1@t1.example",
                password_hash=_hash("AdminPass1234"),
                role="admin",
                is_active=True,
                tenant_id=t1.id,
            ),
            User(
                username="rd_a2",
                email="a2@t2.example",
                password_hash=_hash("AdminPass1234"),
                role="admin",
                is_active=True,
                tenant_id=t2.id,
            ),
            StoreSettings(store_name="Shop A", tenant_id=t1.id, receipt_footer="Footer A"),
            StoreSettings(store_name="Shop B", tenant_id=t2.id, receipt_footer="Footer B"),
        ]
    )
    db_session.commit()

    tok1 = _login(client, "rd_a1")["access_token"]
    tok2 = _login(client, "rd_a2")["access_token"]
    s1 = client.get("/api/store-settings", headers=_auth(tok1)).json()
    s2 = client.get("/api/store-settings", headers=_auth(tok2)).json()
    assert s1["store_name"] == "Shop A"
    assert s1["receipt_footer"] == "Footer A"
    assert s2["store_name"] == "Shop B"
    assert s2["receipt_footer"] == "Footer B"

    client.put(
        "/api/store-settings",
        headers=_auth(tok1),
        json={
            "store_name": "Shop A",
            "low_stock_email_enabled": False,
            "default_low_stock_threshold": 10,
            "receipt_footer": "Changed A",
        },
    )
    s2_after = client.get("/api/store-settings", headers=_auth(tok2)).json()
    assert s2_after["receipt_footer"] == "Footer B"


def test_store_settings_template_has_receipt_design_section():
    html = (ROOT / "templates" / "store-settings.html").read_text(encoding="utf-8")
    assert "Receipt Design" in html
    assert 'id="receipt-keep-for-refund"' in html
    assert 'id="receipt-footer"' in html
    assert 'id="receipt-phone-1"' in html
    assert 'id="receipt-phone-2"' in html
    assert 'id="receipt-phone-3"' in html
    assert 'id="receipt-phone-4"' not in html


def test_js_receipt_closing_helpers_exist():
    receipt_js = (ROOT / "static" / "js" / "receipt.js").read_text(encoding="utf-8")
    escpos_js = (ROOT / "static" / "js" / "receipt-escpos.js").read_text(encoding="utf-8")
    assert "saleReceiptClosingHtml" in receipt_js
    assert "DEFAULT_KEEP_FOR_REFUND" in receipt_js
    assert "appendSaleClosing" in escpos_js
    assert "Keep receipt for refund" in receipt_js
