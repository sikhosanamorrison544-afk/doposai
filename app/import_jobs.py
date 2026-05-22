"""Inventory import jobs stored in PostgreSQL (works with multiple app pods)."""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import ImportJob, User

logger = logging.getLogger(__name__)

_STALE_MINUTES = 45
_running: set[str] = set()
_running_lock = threading.Lock()


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _serialize_payload(products_data: List[dict], import_meta: Optional[dict]) -> str:
    return json.dumps(
        {"products": products_data, "meta": import_meta or {}},
        default=_json_default,
    )


def _deserialize_payload(raw: str) -> tuple[List[dict], dict]:
    data = json.loads(raw)
    products: List[dict] = []
    for row in data.get("products") or []:
        item = dict(row)
        for key in ("cost", "price"):
            if key in item and item[key] is not None:
                item[key] = Decimal(str(item[key]))
        products.append(item)
    return products, data.get("meta") or {}


def _job_to_dict(job: ImportJob) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "job_id": job.id,
        "status": job.status,
        "tenant_id": job.tenant_id,
        "user_id": job.user_id,
        "total_rows": job.total_rows,
        "processed": job.processed,
        "error": job.error,
        "result": None,
    }
    if job.result_json:
        try:
            out["result"] = json.loads(job.result_json)
        except json.JSONDecodeError:
            out["result"] = None
    return out


def create_job(
    db: Session,
    *,
    tenant_id: Optional[int],
    user_id: int,
    total_rows: int,
    products_data: List[dict],
    import_meta: Optional[dict] = None,
) -> str:
    job_id = str(uuid.uuid4())
    row = ImportJob(
        id=job_id,
        tenant_id=tenant_id,
        user_id=user_id,
        status="queued",
        total_rows=total_rows,
        processed=0,
        payload_json=_serialize_payload(products_data, import_meta),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    logger.info("Import job %s queued (%s rows)", job_id, total_rows)
    return job_id


def get_job(db: Session, job_id: str) -> Optional[Dict[str, Any]]:
    row = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not row:
        return None
    _mark_stale_failed(db, row)
    db.refresh(row)
    return _job_to_dict(row)


def job_visible_to_user(job: Dict[str, Any], user: User) -> bool:
    if job.get("user_id") != user.id:
        return False
    from . import tenant_scope

    return job.get("tenant_id") == tenant_scope.tenant_id_for_row(user)


def _mark_stale_failed(db: Session, job: ImportJob) -> None:
    if job.status != "processing":
        return
    cutoff = datetime.utcnow() - timedelta(minutes=_STALE_MINUTES)
    if job.updated_at and job.updated_at < cutoff:
        job.status = "failed"
        job.error = "Import timed out on the server. Try again or split the file."
        job.updated_at = datetime.utcnow()
        db.commit()


def _try_claim_job(db: Session, job_id: str) -> Optional[ImportJob]:
    """Atomically move queued -> processing (works across DB drivers)."""
    updated = (
        db.query(ImportJob)
        .filter(ImportJob.id == job_id, ImportJob.status == "queued")
        .update(
            {"status": "processing", "updated_at": datetime.utcnow()},
            synchronize_session=False,
        )
    )
    if not updated:
        db.rollback()
        return None
    db.commit()
    return db.query(ImportJob).filter(ImportJob.id == job_id).first()


def kick_job(job_id: str) -> None:
    """Start processing on this pod if the job is queued and not already running here."""
    with _running_lock:
        if job_id in _running:
            return

    db = SessionLocal()
    try:
        row = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if not row:
            return
        if row.status == "queued":
            row = _try_claim_job(db, job_id)
            if not row:
                return
        elif row.status != "processing":
            return

        with _running_lock:
            if job_id in _running:
                return
            _running.add(job_id)
    finally:
        db.close()

    thread = threading.Thread(
        target=_run_import_job,
        args=(job_id,),
        name=f"import-{job_id[:8]}",
        daemon=True,
    )
    thread.start()


def _update_progress(job_id: str, processed: int, total: int) -> None:
    db = SessionLocal()
    try:
        row = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if row:
            row.processed = processed
            row.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _run_import_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if not row or not row.payload_json:
            raise RuntimeError("Import job payload missing")

        products_data, import_meta = _deserialize_payload(row.payload_json)
        user = db.query(User).filter(User.id == row.user_id).first()
        if not user:
            raise RuntimeError("User not found for import job")

        from .inventory_import import import_products_into_db

        def on_progress(processed: int, total: int) -> None:
            _update_progress(job_id, processed, total)

        result = import_products_into_db(
            db,
            user,
            products_data,
            None,
            progress_callback=on_progress,
        )
        if import_meta:
            result["columns_mapped"] = import_meta.get("columns_mapped", {})
            if import_meta.get("stock_mode"):
                result["stock_mode"] = import_meta["stock_mode"]

        row = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if row:
            row.status = "complete"
            row.processed = result.get("total_rows", row.total_rows)
            row.result_json = json.dumps(result, default=_json_default)
            row.updated_at = datetime.utcnow()
            db.commit()
        logger.info("Import job %s complete", job_id)
    except Exception as e:
        logger.error("Import job %s failed: %s", job_id, e, exc_info=True)
        try:
            row = db.query(ImportJob).filter(ImportJob.id == job_id).first()
            if row:
                row.status = "failed"
                row.error = str(e)
                row.updated_at = datetime.utcnow()
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
        with _running_lock:
            _running.discard(job_id)


def start_import_job(
    job_id: str,
    user_id: int,
    products_data: List[dict],
    import_meta: Optional[dict] = None,
) -> None:
    """Backward-compatible: kick an already-persisted job."""
    kick_job(job_id)
