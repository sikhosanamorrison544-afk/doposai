"""Optional Firestore sync for tenant subscription security records."""
import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable, Dict, Optional, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

# Firestore collection names (security / billing plane; Postgres = POS transactional data)
COLLECTION_TENANTS = "tenants"
COLLECTION_DEVICES = "devices"
COLLECTION_SUBSCRIPTIONS = "subscriptions"
COLLECTION_BILLING_EVENTS = "billing_events"
COLLECTION_TENANT_SECURITY = "tenant_security"


FIRESTORE_TIMEOUT_SEC = float(os.getenv("FIRESTORE_TIMEOUT_SEC", "8"))


def _run_with_timeout(fn: Callable[[], T], label: str) -> Optional[T]:
    """Avoid blocking HTTP workers on slow Firestore (gateway 502)."""
    if FIRESTORE_TIMEOUT_SEC <= 0:
        return fn()
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn)
        try:
            return fut.result(timeout=FIRESTORE_TIMEOUT_SEC)
        except FuturesTimeout:
            logger.warning(
                "Firestore %s timed out after %.0fs", label, FIRESTORE_TIMEOUT_SEC
            )
            return None


def is_firestore_configured() -> bool:
    return bool(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("FIREBASE_PROJECT_ID")
    )


def _ensure_firebase_app() -> bool:
    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        return False
    try:
        firebase_admin.get_app()
        return True
    except ValueError:
        pass
    try:
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if cred_path and os.path.isfile(cred_path):
            firebase_admin.initialize_app(credentials.Certificate(cred_path))
        else:
            firebase_admin.initialize_app()
        return True
    except Exception as e:
        logger.error("Firebase init failed: %s", e, exc_info=True)
        return False


def upsert_tenant_security_record(
    tenant_uid: str,
    data: Dict[str, Any],
) -> Optional[str]:
    if not is_firestore_configured():
        logger.info("Firestore not configured; skipping tenant cloud record.")
        return None
    try:
        from firebase_admin import firestore
    except ImportError:
        logger.warning("firebase-admin not installed; skipping Firestore.")
        return None
    if not _ensure_firebase_app():
        return None

    def _upsert() -> Optional[str]:
        db = firestore.client()
        doc_ref = db.collection(COLLECTION_TENANTS).document(tenant_uid)
        doc_ref.set(data, merge=True)
        return doc_ref.id

    try:
        result = _run_with_timeout(_upsert, "upsert_tenant_security_record")
        if result is None and FIRESTORE_TIMEOUT_SEC > 0:
            logger.warning("Firestore upsert skipped or timed out for %s", tenant_uid)
        return result
    except Exception as e:
        logger.error("Firestore upsert failed: %s", e, exc_info=True)
        return None


def fetch_tenant_subscription(tenant_uid: str) -> Optional[Dict[str, Any]]:
    if not is_firestore_configured():
        return None
    try:
        from firebase_admin import firestore
    except ImportError:
        return None
    if not _ensure_firebase_app():
        return None
    try:
        db = firestore.client()
        snap = db.collection(COLLECTION_TENANTS).document(tenant_uid).get()
        if snap.exists:
            return dict(snap.to_dict() or {})
    except Exception as e:
        logger.warning("Firestore fetch failed: %s", e)
    return None


def upsert_device_record(device_id: str, data: Dict[str, Any]) -> Optional[str]:
    """Bind app installs to tenants; anti–trial-abuse / reinstall signals (implement policy later)."""
    if not is_firestore_configured():
        return None
    try:
        from firebase_admin import firestore
    except ImportError:
        return None
    if not _ensure_firebase_app():
        return None
    try:
        db = firestore.client()
        ref = db.collection(COLLECTION_DEVICES).document(device_id)
        ref.set(data, merge=True)
        return ref.id
    except Exception as e:
        logger.warning("Firestore device upsert failed: %s", e)
    return None


def sync_subscription_firestore(tenant_uid: str, data: Dict[str, Any]) -> None:
    """Subscriptions + tenant_security billing plane after Paynow activation."""
    if not tenant_uid:
        return
    payload = {**data, "tenant_uid": tenant_uid}
    upsert_tenant_security_record(tenant_uid, payload)
    if not is_firestore_configured():
        return
    try:
        from firebase_admin import firestore
    except ImportError:
        return
    if not _ensure_firebase_app():
        return
    try:
        db = firestore.client()
        db.collection(COLLECTION_SUBSCRIPTIONS).document(tenant_uid).set(payload, merge=True)
        db.collection(COLLECTION_TENANT_SECURITY).document(tenant_uid).set(
            {
                "subscription_status": data.get("subscription_status"),
                "subscription_end": data.get("subscription_end"),
                "billing_status": data.get("billing_status"),
                "payment_verified": data.get("payment_verified", False),
                "updated_at": data.get("updated_at"),
            },
            merge=True,
        )
    except Exception as e:
        logger.warning("Firestore subscription sync failed: %s", e)


def append_billing_event(event_id: str, data: Dict[str, Any]) -> Optional[str]:
    """Immutable billing audit trail (webhooks, trial conversions)."""
    if not is_firestore_configured():
        return None
    try:
        from firebase_admin import firestore
    except ImportError:
        return None
    if not _ensure_firebase_app():
        return None
    try:
        db = firestore.client()
        ref = db.collection(COLLECTION_BILLING_EVENTS).document(event_id)
        ref.set(data, merge=False)
        return ref.id
    except Exception as e:
        logger.warning("Firestore billing event write failed: %s", e)
    return None
