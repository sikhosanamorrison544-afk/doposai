"""Background inventory import jobs (avoids HTTP gateway timeouts on large CSVs)."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from .database import SessionLocal
from .models import User

logger = logging.getLogger(__name__)

_JOB_TTL_SECONDS = 3600
_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}


def _prune_old_jobs() -> None:
    now = time.time()
    stale = [
        jid
        for jid, job in _jobs.items()
        if now - float(job.get("created_at", now)) > _JOB_TTL_SECONDS
    ]
    for jid in stale:
        _jobs.pop(jid, None)


def create_job(*, tenant_id: Optional[int], user_id: int, total_rows: int) -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _prune_old_jobs()
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "processing",
            "tenant_id": tenant_id,
            "user_id": user_id,
            "total_rows": total_rows,
            "processed": 0,
            "result": None,
            "error": None,
            "created_at": time.time(),
        }
    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def job_visible_to_user(job: Dict[str, Any], user: User) -> bool:
    if job.get("user_id") != user.id:
        return False
    from . import tenant_scope

    job_tid = job.get("tenant_id")
    user_tid = tenant_scope.tenant_id_for_row(user)
    return job_tid == user_tid


def run_import_job(
    job_id: str,
    user_id: int,
    products_data: List[dict],
    import_meta: Optional[dict] = None,
) -> None:
    """Run import in a background thread (own DB session)."""
    db = SessionLocal()
    try:
        from .inventory_import import import_products_into_db

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise RuntimeError("User not found for import job")

        result = import_products_into_db(db, user, products_data, None)
        if import_meta:
            result["columns_mapped"] = import_meta.get("columns_mapped", {})
            if import_meta.get("stock_mode"):
                result["stock_mode"] = import_meta["stock_mode"]

        with _lock:
            job = _jobs.get(job_id)
            if job:
                job["status"] = "complete"
                job["result"] = result
                job["processed"] = result.get("total_rows", job.get("total_rows", 0))
    except Exception as e:
        logger.error("Import job %s failed: %s", job_id, e, exc_info=True)
        with _lock:
            job = _jobs.get(job_id)
            if job:
                job["status"] = "failed"
                job["error"] = str(e)
    finally:
        db.close()


def start_import_job(
    job_id: str,
    user_id: int,
    products_data: List[dict],
    import_meta: Optional[dict] = None,
) -> None:
    thread = threading.Thread(
        target=run_import_job,
        args=(job_id, user_id, products_data, import_meta),
        name=f"import-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
