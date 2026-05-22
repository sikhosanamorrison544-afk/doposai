#!/bin/sh
set -e
# Postgres: Alembic + idempotent billing table bootstrap (subscriptions, payments, logs).
if [ -n "${DATABASE_URL:-}" ] && echo "$DATABASE_URL" | grep -q '^postgresql'; then
  set +e
  alembic upgrade head
  _alembic_rc=$?
  set -e
  if [ "$_alembic_rc" != 0 ]; then
    echo "WARN: alembic upgrade head exited ${_alembic_rc}"
  fi
  python3 migrate_billing_paynow.py || {
    echo "ERROR: migrate_billing_paynow.py failed"
    exit 1
  }
  python3 migrate_enterprise.py || {
    echo "ERROR: migrate_enterprise.py failed"
    exit 1
  }
  python3 migrate_refunds.py || {
    echo "ERROR: migrate_refunds.py failed"
    exit 1
  }
  python3 migrate_import_jobs.py || {
    echo "ERROR: migrate_import_jobs.py failed"
    exit 1
  }
  python3 migrate_whatsapp.py || {
    echo "ERROR: migrate_whatsapp.py failed"
    exit 1
  }
  # Strip the legacy "J & B MALL" default brand from existing rows.
  # Idempotent; no-op once the rewrite has happened.
  python3 migrate_remove_legacy_brand.py || {
    echo "WARN: migrate_remove_legacy_brand.py failed (non-fatal)"
  }
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
