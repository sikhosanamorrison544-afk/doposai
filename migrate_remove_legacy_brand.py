"""One-shot migration: replace the legacy hardcoded default brand.

Older deployments seeded a StoreSettings row whose ``store_name`` was the
literal historical default (``J & B MALL``). New deployments use whatever
the operator sets via ``PLATFORM_BRAND_NAME``. This script rewrites the
old default in place so the legacy text doesn't keep showing on the login
screen / receipts / admin header.

Safety:
  * Only rewrites rows whose ``store_name`` exactly matches one of the
    known legacy default strings — never touches a tenant that actually
    chose that name themselves (improbable, but a precondition we keep).
  * Idempotent: running it twice is a no-op the second time.
  * Skips rows associated with a specific ``tenant_id``; we only touch
    the platform-default row (``tenant_id IS NULL``) so per-tenant
    overrides remain authoritative.

Run manually:
    python3 migrate_remove_legacy_brand.py

It is also wired into ``scripts/render_start.sh`` so it runs on every
deploy without operator action.
"""
from __future__ import annotations

import logging
import sys


LEGACY_DEFAULT_NAMES = {
    "J & B MALL",
    "J&B MALL",
    "J AND B MALL",
}


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("migrate_remove_legacy_brand")

    # Pull in the FULL model graph before opening a session — StoreSettings
    # has a foreign key to ``tenants.id``, and without app.main being
    # imported the Tenant model isn't registered, so SQLAlchemy raises
    # NoReferencedTableError as soon as we query.
    import app.main  # noqa: F401 — registers every ORM model
    from app.config import PLATFORM_BRAND_NAME
    from app.database import SessionLocal
    from app.models import StoreSettings

    target = PLATFORM_BRAND_NAME.strip() or "All In One POS"

    db = SessionLocal()
    try:
        rows = db.query(StoreSettings).all()
        if not rows:
            log.info("StoreSettings table is empty; nothing to migrate.")
            return 0

        updated = 0
        skipped_tenant_rows = 0
        skipped_other = 0
        for r in rows:
            tenant_id = getattr(r, "tenant_id", None)
            current = (r.store_name or "").strip()
            if current.upper() not in {n.upper() for n in LEGACY_DEFAULT_NAMES}:
                skipped_other += 1
                continue
            if tenant_id is not None:
                # A real tenant — leave it alone even if the name matches
                # the legacy default, in case they genuinely chose it.
                skipped_tenant_rows += 1
                log.warning(
                    "StoreSettings id=%s tenant_id=%s store_name=%r matches the "
                    "legacy default but is tied to a tenant; leaving untouched.",
                    r.id, tenant_id, current,
                )
                continue
            log.info(
                "Rewriting StoreSettings id=%s tenant_id=NULL: %r -> %r",
                r.id, current, target,
            )
            r.store_name = target
            updated += 1

        if updated:
            db.commit()
            log.info(
                "Done. Updated %d row(s); skipped %d non-legacy row(s); "
                "skipped %d tenant-owned legacy row(s).",
                updated, skipped_other, skipped_tenant_rows,
            )
        else:
            log.info(
                "No rows needed updating. (%d non-legacy row(s) checked, "
                "%d tenant-owned legacy row(s) intentionally left.)",
                skipped_other, skipped_tenant_rows,
            )
        return 0
    except Exception:
        db.rollback()
        log.exception("migrate_remove_legacy_brand failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
