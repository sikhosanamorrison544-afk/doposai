#!/bin/sh
# Bind PORT immediately for Render's port scan; run DB migrations in the background.
set -e

_run_migrations() {
  echo "[migrate] background migrations starting"
  if [ -n "${DATABASE_URL:-}" ] && echo "$DATABASE_URL" | grep -q '^postgresql'; then
    set +e
    alembic upgrade head
    _alembic_rc=$?
    set -e
    if [ "$_alembic_rc" != 0 ]; then
      echo "WARN: alembic upgrade head exited ${_alembic_rc}"
    fi
    python3 migrate_billing_paynow.py || {
      echo "WARN: migrate_billing_paynow.py failed (non-fatal)"
    }
    python3 migrate_enterprise.py || {
      echo "WARN: migrate_enterprise.py failed (non-fatal)"
    }
    python3 migrate_refunds.py || {
      echo "WARN: migrate_refunds.py failed (non-fatal)"
    }
    python3 migrate_import_jobs.py || {
      echo "WARN: migrate_import_jobs.py failed (non-fatal)"
    }
    python3 migrate_whatsapp.py || {
      echo "WARN: migrate_whatsapp.py failed (non-fatal)"
    }
    python3 migrate_remove_legacy_brand.py || {
      echo "WARN: migrate_remove_legacy_brand.py failed (non-fatal)"
    }
    python3 migrate_analytics_indexes.py || {
      echo "WARN: migrate_analytics_indexes.py failed (non-fatal)"
    }
    python3 migrate_product_name_length.py || {
      echo "WARN: migrate_product_name_length.py failed (non-fatal)"
    }
  fi
  echo "[migrate] background migrations finished"
}

if [ "${SKIP_STARTUP_MIGRATIONS:-0}" != "1" ]; then
  _run_migrations &
else
  echo "[migrate] SKIP_STARTUP_MIGRATIONS=1 — skipped"
fi

PORT="${PORT:-8000}"
WORKERS="${WEB_CONCURRENCY:-2}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-180}"

if [ "${USE_UVICORN_ONLY:-0}" = "1" ]; then
  echo "[start] uvicorn only (USE_UVICORN_ONLY=1) on 0.0.0.0:${PORT}"
  exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips='*'
fi

echo "[start] gunicorn + uvicorn workers=${WORKERS} timeout=${GUNICORN_TIMEOUT}s on 0.0.0.0:${PORT}"
exec gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w "$WORKERS" \
  -b "0.0.0.0:${PORT}" \
  --timeout "$GUNICORN_TIMEOUT" \
  --graceful-timeout 60 \
  --keep-alive 5 \
  --forwarded-allow-ips='*' \
  --access-logfile - \
  --error-logfile -
