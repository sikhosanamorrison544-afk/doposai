"""Tests for the Meta webhook envelope → InboundMessage parser."""
from app.whatsapp.parser import parse_inbound_messages


def _envelope(messages):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {"value": {"messaging_product": "whatsapp", "messages": messages}}
                ],
            }
        ],
    }


def test_parses_plain_text():
    out = parse_inbound_messages(
        _envelope(
            [
                {
                    "from": "263770000000",
                    "id": "wamid.AAA",
                    "type": "text",
                    "text": {"body": "  hello there  "},
                }
            ]
        )
    )
    assert len(out) == 1
    msg = out[0]
    assert msg.from_phone == "263770000000"
    assert msg.wa_message_id == "wamid.AAA"
    assert msg.message_type == "text"
    assert msg.text == "hello there"
    assert msg.interactive_id is None


def test_parses_list_reply():
    out = parse_inbound_messages(
        _envelope(
            [
                {
                    "from": "263770000000",
                    "id": "wamid.BBB",
                    "type": "interactive",
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"id": "tenant:7", "title": "Acme Glass"},
                    },
                }
            ]
        )
    )
    assert len(out) == 1
    msg = out[0]
    assert msg.interactive_id == "tenant:7"
    assert msg.text == "Acme Glass"


def test_parses_button_reply():
    out = parse_inbound_messages(
        _envelope(
            [
                {
                    "from": "263770000000",
                    "id": "wamid.CCC",
                    "type": "interactive",
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {"id": "btn_yes", "title": "Yes"},
                    },
                }
            ]
        )
    )
    assert out[0].interactive_id == "btn_yes"
    assert out[0].text == "Yes"


def test_ignores_status_only_envelopes():
    envelope = {
        "object": "whatsapp_business_account",
        "entry": [
            {"id": "x", "changes": [{"value": {"statuses": [{"id": "wamid.X"}]}}]}
        ],
    }
    assert parse_inbound_messages(envelope) == []


def test_image_messages_have_empty_text_but_preserved_raw():
    raw = {
        "from": "263770000000",
        "id": "wamid.DDD",
        "type": "image",
        "image": {"id": "media_123"},
    }
    out = parse_inbound_messages(_envelope([raw]))
    assert out[0].text == ""
    assert out[0].message_type == "image"
    assert out[0].raw == raw
