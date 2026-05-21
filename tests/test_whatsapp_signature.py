"""Tests for Meta webhook HMAC-SHA256 signature verification."""
from app.whatsapp.signature import compute_signature, verify_meta_signature


SECRET = "supersecret"
BODY = b'{"entry":[{"id":"x"}]}'


def test_compute_signature_format():
    sig = compute_signature(SECRET, BODY)
    assert sig.startswith("sha256=")
    assert len(sig) == len("sha256=") + 64  # hex of 32 bytes


def test_verify_accepts_correct_signature():
    sig = compute_signature(SECRET, BODY)
    assert verify_meta_signature(BODY, sig, SECRET) is True


def test_verify_rejects_tampered_body():
    sig = compute_signature(SECRET, BODY)
    assert verify_meta_signature(BODY + b"x", sig, SECRET) is False


def test_verify_rejects_wrong_secret():
    sig = compute_signature(SECRET, BODY)
    assert verify_meta_signature(BODY, sig, "othersecret") is False


def test_verify_rejects_missing_header():
    assert verify_meta_signature(BODY, None, SECRET) is False
    assert verify_meta_signature(BODY, "", SECRET) is False


def test_verify_rejects_bad_prefix():
    sig = compute_signature(SECRET, BODY).replace("sha256=", "md5=")
    assert verify_meta_signature(BODY, sig, SECRET) is False


def test_verify_rejects_empty_secret():
    sig = compute_signature(SECRET, BODY)
    assert verify_meta_signature(BODY, sig, "") is False
