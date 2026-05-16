#!/bin/sh
set -e
# Migrations (Postgres). Never fail the deploy if Alembic has a transient error.
if [ -n "${DATABASE_URL:-}" ] && echo "$DATABASE_URL" | grep -q '^postgresql'; then
  set +e
  alembic upgrade head
  _alembic_rc=$?
  set -e
  if [ "$_alembic_rc" != 0 ]; then
    echo "alembic upgrade head exited ${_alembic_rc} (non-fatal; continuing)"
  fi
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
