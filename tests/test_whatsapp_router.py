"""State machine tests for the WhatsApp router.

These tests use:
  * an in-memory SQLite database with the real ORM metadata,
  * a stubbed ``meta_client`` that records outbound calls instead of
    hitting the Meta Graph API.

That gives us end-to-end coverage of the router without any network or
external services.
"""
from __future__ import annotations

import asyncio
from typing import List

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main  # noqa: F401 — registers every ORM model with the metadata
from app.database import Base
from app.quotation_models import Tenant
from app.models import Product, StoreSettings  # noqa: F401 — ensure mapped
from app.whatsapp import meta_client, router as wa_router
from app.whatsapp.models import WhatsAppMessage, WhatsAppSession


# ── test fixtures ──────────────────────────────────────────────────────


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def stub_meta(monkeypatch):
    """Capture every outbound message instead of POSTing to Meta."""
    sent: List[dict] = []

    async def fake_send_text(to, body, preview_url=False):
        sent.append({"kind": "text", "to": to, "body": body})
        return meta_client.SendResult(ok=True, wa_message_id=f"wamid.fake.{len(sent)}")

    async def fake_send_list(to, body_text, button_text, sections, header_text=None, footer_text=None):
        sent.append(
            {
                "kind": "list",
                "to": to,
                "body": body_text,
                "sections": [
                    {"title": s.title, "rows": [(r.id, r.title) for r in s.rows]}
                    for s in sections
                ],
            }
        )
        return meta_client.SendResult(ok=True, wa_message_id=f"wamid.list.{len(sent)}")

    monkeypatch.setattr(meta_client, "send_text", fake_send_text)
    monkeypatch.setattr(meta_client, "send_list", fake_send_list)
    return sent


def _make_tenant(db, **kwargs):
    defaults = dict(
        tenant_uid=kwargs.get("name", "t") + "-uid",
        name="Acme",
        is_active=True,
        whatsapp_enabled=True,
        subscription_status="active",
    )
    defaults.update(kwargs)
    t = Tenant(**defaults)
    db.add(t)
    db.flush()
    return t


def _make_product(db, *, tenant_id, name, price=10.0, stock=5.0, barcode=None):
    p = Product(
        name=name,
        barcode=barcode,
        selling_price=price,
        cost_price=price,
        stock_qty=stock,
        reserved_qty=0,
        is_active=True,
        tenant_id=tenant_id,
    )
    db.add(p)
    db.flush()
    return p


def _msg(text="", *, mtype="text", interactive_id=None, frm="263770000000"):
    return wa_router.InboundMessage(
        from_phone=frm,
        wa_message_id="wamid.test",
        message_type=mtype,
        text=text,
        interactive_id=interactive_id,
        raw={"from": frm, "type": mtype, "text": {"body": text}},
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── scenarios ──────────────────────────────────────────────────────────


def test_first_message_sends_welcome_list(db_session, stub_meta):
    _make_tenant(db_session, name="Acme Glass", whatsapp_keyword="GLASS")
    _make_tenant(db_session, name="Beta Solar", whatsapp_keyword="SOLAR")
    db_session.commit()

    _run(wa_router.handle_inbound(db_session, _msg("hi")))

    assert len(stub_meta) == 1
    sent = stub_meta[0]
    assert sent["kind"] == "list"
    titles = [r[1] for s in sent["sections"] for r in s["rows"]]
    assert "Acme Glass" in titles
    assert "Beta Solar" in titles

    sess = db_session.get(WhatsAppSession, "263770000000")
    assert sess is not None
    assert sess.current_state == "menu"
    assert sess.selected_tenant_id is None


def test_numeric_pick_selects_tenant(db_session, stub_meta):
    _make_tenant(db_session, name="Acme Glass", whatsapp_keyword="GLASS")
    _make_tenant(db_session, name="Beta Solar", whatsapp_keyword="SOLAR")
    db_session.commit()

    _run(wa_router.handle_inbound(db_session, _msg("hi")))  # welcome list
    stub_meta.clear()
    _run(wa_router.handle_inbound(db_session, _msg("1")))  # pick Acme Glass

    sess = db_session.get(WhatsAppSession, "263770000000")
    assert sess.current_state == "in_business"
    assert sess.selected_tenant_id is not None

    assert len(stub_meta) == 1
    assert stub_meta[0]["kind"] == "text"
    assert "Acme Glass" in stub_meta[0]["body"]


def test_keyword_routes_directly_to_business(db_session, stub_meta):
    _make_tenant(db_session, name="Acme Glass", whatsapp_keyword="GLASS")
    _make_tenant(db_session, name="Beta Solar", whatsapp_keyword="SOLAR")
    db_session.commit()

    _run(wa_router.handle_inbound(db_session, _msg("SOLAR")))

    sess = db_session.get(WhatsAppSession, "263770000000")
    beta = db_session.query(Tenant).filter_by(name="Beta Solar").one()
    assert sess.selected_tenant_id == beta.id
    assert sess.current_state == "in_business"


def test_keyword_inside_sentence_is_whole_word(db_session, stub_meta):
    _make_tenant(db_session, name="Acme Glass", whatsapp_keyword="GLASS")
    db_session.commit()

    _run(wa_router.handle_inbound(db_session, _msg("I want fiberglass info")))
    sess = db_session.get(WhatsAppSession, "263770000000")
    assert sess.current_state == "menu"  # "fiberglass" must NOT match "GLASS"

    _run(wa_router.handle_inbound(db_session, _msg("Need GLASS please")))
    sess = db_session.get(WhatsAppSession, "263770000000")
    assert sess.current_state == "in_business"


def test_list_reply_id_selects_tenant(db_session, stub_meta):
    t = _make_tenant(db_session, name="Acme Glass", whatsapp_keyword="GLASS")
    db_session.commit()

    _run(
        wa_router.handle_inbound(
            db_session,
            _msg("Acme Glass", mtype="interactive", interactive_id=f"tenant:{t.id}"),
        )
    )

    sess = db_session.get(WhatsAppSession, "263770000000")
    assert sess.selected_tenant_id == t.id
    assert sess.current_state == "in_business"


def test_product_search_returns_tenant_scoped_hits(db_session, stub_meta):
    glass = _make_tenant(db_session, name="Acme Glass", whatsapp_keyword="GLASS")
    solar = _make_tenant(db_session, name="Beta Solar", whatsapp_keyword="SOLAR")
    _make_product(db_session, tenant_id=glass.id, name="5mm clear glass", price=12.5, stock=20)
    _make_product(db_session, tenant_id=solar.id, name="5mm solar panel", price=99.0, stock=3)
    db_session.commit()

    _run(wa_router.handle_inbound(db_session, _msg("GLASS")))
    stub_meta.clear()
    _run(wa_router.handle_inbound(db_session, _msg("do you have 5mm clear glass?")))

    assert any("5mm clear glass" in m["body"] for m in stub_meta)
    # Solar's product must NEVER be mentioned for a Glass customer
    assert not any("solar panel" in m["body"].lower() for m in stub_meta)


def test_handover_state_silences_bot(db_session, stub_meta):
    _make_tenant(db_session, name="Acme Glass", whatsapp_keyword="GLASS")
    db_session.commit()

    _run(wa_router.handle_inbound(db_session, _msg("GLASS")))
    stub_meta.clear()

    _run(wa_router.handle_inbound(db_session, _msg("AGENT")))
    assert len(stub_meta) == 1  # the handover acknowledgement

    stub_meta.clear()
    _run(wa_router.handle_inbound(db_session, _msg("are you there?")))
    assert stub_meta == []  # bot stays silent in handover

    sess = db_session.get(WhatsAppSession, "263770000000")
    assert sess.current_state == "handover"


def test_menu_command_resets_session(db_session, stub_meta):
    _make_tenant(db_session, name="Acme Glass", whatsapp_keyword="GLASS")
    db_session.commit()

    _run(wa_router.handle_inbound(db_session, _msg("GLASS")))
    _run(wa_router.handle_inbound(db_session, _msg("MENU")))

    sess = db_session.get(WhatsAppSession, "263770000000")
    assert sess.current_state == "menu"
    assert sess.selected_tenant_id is None


def test_inbound_message_is_audit_logged(db_session, stub_meta):
    _make_tenant(db_session, name="Acme Glass", whatsapp_keyword="GLASS")
    db_session.commit()

    _run(wa_router.handle_inbound(db_session, _msg("GLASS")))
    msgs = db_session.query(WhatsAppMessage).all()
    directions = sorted({m.direction for m in msgs})
    assert directions == ["in", "out"]
    assert any(m.body == "GLASS" for m in msgs if m.direction == "in")


def test_disabled_tenant_is_excluded_from_menu(db_session, stub_meta):
    _make_tenant(db_session, name="Visible", whatsapp_keyword="VIS")
    _make_tenant(db_session, name="Hidden", whatsapp_keyword="HID", whatsapp_enabled=False)
    db_session.commit()

    _run(wa_router.handle_inbound(db_session, _msg("hi")))

    sent = stub_meta[-1]
    titles = [r[1] for s in sent["sections"] for r in s["rows"]]
    assert "Visible" in titles
    assert "Hidden" not in titles


def test_keyword_for_disabled_tenant_does_not_route(db_session, stub_meta):
    _make_tenant(db_session, name="Hidden", whatsapp_keyword="HID", whatsapp_enabled=False)
    db_session.commit()

    _run(wa_router.handle_inbound(db_session, _msg("HID")))
    sess = db_session.get(WhatsAppSession, "263770000000")
    assert sess.current_state == "menu"
