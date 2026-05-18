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
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
