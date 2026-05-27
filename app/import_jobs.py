"""Inventory import jobs stored in PostgreSQL (works with multiple app pods)."""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import ImportJob, User
from .startup_config import IMPORT_TEMP_DIR

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


def ensure_import_temp_dir() -> str:
    os.makedirs(IMPORT_TEMP_DIR, exist_ok=True)
    return IMPORT_TEMP_DIR


def remove_temp_file(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError as e:
        logger.warning("Could not remove import temp file %s: %s", path, e)


def create_awaiting_upload_job(
    db: Session,
    *,
    tenant_id: Optional[int],
    user_id: int,
    file_name: str,
    file_ext: str,
    size_bytes: int = 0,
) -> tuple[str, str]:
    """Reserve a job id and temp path before the client uploads the file body."""
    job_id = str(uuid.uuid4())
    ensure_import_temp_dir()
    temp_path = os.path.join(IMPORT_TEMP_DIR, f"{job_id}{file_ext or '.csv'}")
    row = ImportJob(
        id=job_id,
        tenant_id=tenant_id,
        user_id=user_id,
        status="awaiting_upload",
        total_rows=0,
        processed=0,
        file_name=file_name,
        file_ext=file_ext,
        file_bytes=None,
        payload_json=json.dumps(
            {"file_path": temp_path, "size_bytes": size_bytes, "meta": {}},
            default=_json_default,
        ),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    logger.info("Import job %s awaiting upload (%s)", job_id, file_name)
    return job_id, temp_path


def finalize_upload_and_queue(job_id: str, *, file_path: str, size_bytes: int) -> None:
    """Mark upload complete and start background processing."""
    db = SessionLocal()
    try:
        row = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if not row:
            raise ValueError("Import job not found")
        if row.status not in ("awaiting_upload", "queued"):
            raise ValueError(f"Import job is not accepting uploads (status={row.status})")
        payload: Dict[str, Any] = {}
        if row.payload_json:
            try:
                payload = json.loads(row.payload_json)
            except json.JSONDecodeError:
                payload = {}
        payload["file_path"] = file_path
        payload["size_bytes"] = size_bytes
        row.payload_json = json.dumps(payload, default=_json_default)
        row.status = "queued"
        row.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
    kick_job(job_id)


def create_job_from_path(
    db: Session,
    *,
    tenant_id: Optional[int],
    user_id: int,
    file_name: str,
    file_ext: str,
    file_path: str,
    size_bytes: int,
    job_id: Optional[str] = None,
) -> str:
    """Queue import from a temp file on disk (avoids huge DB blobs on upload)."""
    job_id = job_id or str(uuid.uuid4())
    row = ImportJob(
        id=job_id,
        tenant_id=tenant_id,
        user_id=user_id,
        status="queued",
        total_rows=0,
        processed=0,
        file_name=file_name,
        file_ext=file_ext,
        file_bytes=None,
        payload_json=json.dumps(
            {"file_path": file_path, "size_bytes": size_bytes, "meta": {}},
            default=_json_default,
        ),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    logger.info(
        "Import job %s queued from disk %s (%s bytes)",
        job_id,
        file_name,
        size_bytes,
    )
    return job_id


def create_job_from_bytes(
    db: Session,
    *,
    tenant_id: Optional[int],
    user_id: int,
    file_name: str,
    file_ext: str,
    content: bytes,
) -> str:
    """Queue import from raw file bytes; parsing runs in the background worker."""
    spill = int(os.environ.get("IMPORT_SPILL_TO_DISK_BYTES", "262144"))
    if len(content) > spill:
        ensure_import_temp_dir()
        job_id = str(uuid.uuid4())
        path = os.path.join(IMPORT_TEMP_DIR, f"{job_id}{file_ext or '.csv'}")
        with open(path, "wb") as f:
            f.write(content)
        return create_job_from_path(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            file_name=file_name,
            file_ext=file_ext,
            file_path=path,
            size_bytes=len(content),
            job_id=job_id,
        )

    job_id = str(uuid.uuid4())
    row = ImportJob(
        id=job_id,
        tenant_id=tenant_id,
        user_id=user_id,
        status="queued",
        total_rows=0,
        processed=0,
        file_name=file_name,
        file_ext=file_ext,
        file_bytes=content,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    logger.info(
        "Import job %s queued from file %s (%s bytes)",
        job_id,
        file_name,
        len(content),
    )
    return job_id


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
    if job.status == "awaiting_upload":
        cutoff = datetime.utcnow() - timedelta(minutes=15)
        if job.updated_at and job.updated_at < cutoff:
            job.status = "failed"
            job.error = "Upload was not completed in time. Start import again."
            job.updated_at = datetime.utcnow()
            db.commit()
        return
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
            if total and not row.total_rows:
                row.total_rows = total
            row.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _load_products_for_job(row: ImportJob) -> tuple[List[dict], dict]:
    from .inventory_upload import parse_inventory_upload

    if row.payload_json:
        try:
            data = json.loads(row.payload_json)
        except json.JSONDecodeError:
            data = {}
        fpath = data.get("file_path")
        if fpath and os.path.isfile(fpath):
            try:
                with open(fpath, "rb") as f:
                    content = f.read()
            finally:
                remove_temp_file(fpath)
            ext = row.file_ext or ".csv"
            products_data, import_meta = parse_inventory_upload(content, ext)
            return products_data, import_meta
        if data.get("products") is not None:
            return _deserialize_payload(row.payload_json)

    if row.file_bytes:
        ext = row.file_ext or ".csv"
        products_data, import_meta = parse_inventory_upload(row.file_bytes, ext)
        return products_data, import_meta

    raise RuntimeError("Import job has no file or payload")


def _run_import_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if not row:
            raise RuntimeError("Import job not found")

        products_data, import_meta = _load_products_for_job(row)

        from .startup_config import MAX_IMPORT_ROWS

        if len(products_data) > MAX_IMPORT_ROWS:
            raise ValueError(
                f"File has {len(products_data)} product rows; maximum is {MAX_IMPORT_ROWS}. "
                "Split the file into smaller CSVs."
            )
        if not products_data:
            raise ValueError("No products found in file")

        row.total_rows = len(products_data)
        row.file_bytes = None
        if row.payload_json:
            try:
                meta = json.loads(row.payload_json)
                if meta.get("file_path"):
                    meta.pop("file_path", None)
                    row.payload_json = json.dumps(meta, default=_json_default)
            except json.JSONDecodeError:
                pass
        row.updated_at = datetime.utcnow()
        db.commit()

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
